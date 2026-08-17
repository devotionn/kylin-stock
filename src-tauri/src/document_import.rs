use serde::Deserialize;
use sqlx::{Connection, Executor, SqliteConnection};
use std::{fs, path::PathBuf};
use tauri::{AppHandle, Manager};
use uuid::Uuid;

const DATABASE_FILE: &str = "kylin-stock.db";
const MAX_ITEMS: usize = 200;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocumentImportLineInput {
    material_id: i64,
    location_id: i64,
    quantity: f64,
    occurred_at: String,
    related_unit: Option<String>,
    handler: Option<String>,
    remark: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScannedDocumentImportInput {
    source_hash: String,
    source_file_name: String,
    document_type: String,
    transfer_basis: Option<String>,
    supplier_unit: Option<String>,
    receiver_unit: Option<String>,
    items: Vec<DocumentImportLineInput>,
}

fn database_path(app: &AppHandle) -> Result<PathBuf, String> {
    let app_config = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("无法获取应用数据目录：{e}"))?;
    fs::create_dir_all(&app_config).map_err(|e| format!("无法创建应用数据目录：{e}"))?;
    Ok(app_config.join(DATABASE_FILE))
}

async fn open_connection(app: &AppHandle) -> Result<SqliteConnection, String> {
    let path = database_path(app)?;
    let url = format!("sqlite:{}", path.to_string_lossy());
    let mut connection = SqliteConnection::connect(&url)
        .await
        .map_err(|e| format!("无法连接业务数据库：{e}"))?;
    configure_connection(&mut connection).await?;
    Ok(connection)
}

async fn configure_connection(connection: &mut SqliteConnection) -> Result<(), String> {
    sqlx::query("PRAGMA foreign_keys = ON")
        .execute(&mut *connection)
        .await
        .map_err(|e| format!("无法启用数据库外键约束：{e}"))?;
    sqlx::query("PRAGMA busy_timeout = 5000")
        .execute(&mut *connection)
        .await
        .map_err(|e| format!("无法设置数据库等待策略：{e}"))?;
    Ok(())
}

fn clean(value: &Option<String>) -> Option<String> {
    value
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn validate(input: &ScannedDocumentImportInput) -> Result<(), String> {
    let hash = input.source_hash.trim();
    if hash.len() != 64 || !hash.chars().all(|ch| ch.is_ascii_hexdigit()) {
        return Err("扫描单据指纹无效，请重新执行识别".into());
    }
    if input.source_file_name.trim().is_empty() || input.source_file_name.chars().count() > 255 {
        return Err("扫描单据文件名无效".into());
    }
    if input.document_type.trim() != "TRANSFER_RECEIVE" {
        return Err("当前仅支持调拨（接收）通知单导入".into());
    }
    if input.items.is_empty() {
        return Err("单据至少需要一条物资明细".into());
    }
    if input.items.len() > MAX_ITEMS {
        return Err(format!("单张单据最多允许 {MAX_ITEMS} 条物资明细"));
    }
    for (index, item) in input.items.iter().enumerate() {
        if item.material_id <= 0 {
            return Err(format!("第 {} 行：请选择物资", index + 1));
        }
        if item.location_id <= 0 {
            return Err(format!("第 {} 行：请选择存放位置", index + 1));
        }
        if !item.quantity.is_finite() || item.quantity <= 0.0 {
            return Err(format!("第 {} 行：数量必须大于 0", index + 1));
        }
        if item.occurred_at.trim().is_empty() {
            return Err(format!("第 {} 行：请选择业务时间", index + 1));
        }
    }
    Ok(())
}

async fn begin_immediate(connection: &mut SqliteConnection) -> Result<(), String> {
    sqlx::query("BEGIN IMMEDIATE")
        .execute(connection)
        .await
        .map(|_| ())
        .map_err(|e| format!("无法开始单据入库事务：{e}"))
}

async fn rollback(connection: &mut SqliteConnection) {
    let _ = sqlx::query("ROLLBACK").execute(connection).await;
}

async fn commit(connection: &mut SqliteConnection) -> Result<(), String> {
    sqlx::query("COMMIT")
        .execute(connection)
        .await
        .map(|_| ())
        .map_err(|e| format!("单据入库事务提交失败：{e}"))
}

fn transaction_no() -> String {
    format!("IN-{}", Uuid::new_v4().simple())
}

async fn insert_item(
    connection: &mut SqliteConnection,
    item: &DocumentImportLineInput,
    number: &str,
) -> Result<(), String> {
    sqlx::query(
        r#"INSERT INTO stock_transactions
          (transaction_no,type,material_id,location_id,quantity,occurred_at,related_unit,destination,handler,receiver,remark,created_at)
          VALUES (?,'IN',?,?,?,?,?,NULL,?,NULL,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))"#,
    )
    .bind(number)
    .bind(item.material_id)
    .bind(item.location_id)
    .bind(item.quantity)
    .bind(item.occurred_at.trim())
    .bind(clean(&item.related_unit))
    .bind(clean(&item.handler))
    .bind(clean(&item.remark))
    .execute(&mut *connection)
    .await
    .map_err(|e| e.to_string())?;

    sqlx::query(
        r#"INSERT INTO inventory_balances(material_id,location_id,quantity,updated_at)
           VALUES (?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT(material_id,location_id) DO UPDATE SET
           quantity = quantity + excluded.quantity,
           updated_at = excluded.updated_at"#,
    )
    .bind(item.material_id)
    .bind(item.location_id)
    .bind(item.quantity)
    .execute(&mut *connection)
    .await
    .map_err(|e| e.to_string())?;
    Ok(())
}

async fn import_on_connection(
    connection: &mut SqliteConnection,
    input: &ScannedDocumentImportInput,
) -> Result<Vec<String>, String> {
    validate(input)?;
    begin_immediate(connection).await?;

    let source_hash = input.source_hash.trim().to_ascii_lowercase();
    let existing = match sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM document_imports WHERE source_hash=?",
    )
    .bind(&source_hash)
    .fetch_one(&mut *connection)
    .await
    {
        Ok(value) => value,
        Err(error) => {
            rollback(connection).await;
            return Err(format!("无法检查单据重复状态：{error}"));
        }
    };
    if existing > 0 {
        rollback(connection).await;
        return Err("该扫描单据已经导入过。为防止库存重复增加，本次操作已取消。".into());
    }

    let mut numbers = Vec::with_capacity(input.items.len());
    for (index, item) in input.items.iter().enumerate() {
        let number = transaction_no();
        if let Err(error) = insert_item(connection, item, &number).await {
            rollback(connection).await;
            return Err(format!("单据第 {} 行入库失败，整张单据已回滚：{error}", index + 1));
        }
        numbers.push(number);
    }

    let numbers_json = match serde_json::to_string(&numbers) {
        Ok(value) => value,
        Err(error) => {
            rollback(connection).await;
            return Err(format!("无法生成单据流水索引：{error}"));
        }
    };
    let record_result = sqlx::query(
        r#"INSERT INTO document_imports
          (source_hash,source_file_name,document_type,transfer_basis,supplier_unit,receiver_unit,line_count,transaction_numbers,created_at)
          VALUES (?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))"#,
    )
    .bind(&source_hash)
    .bind(input.source_file_name.trim())
    .bind(input.document_type.trim())
    .bind(clean(&input.transfer_basis))
    .bind(clean(&input.supplier_unit))
    .bind(clean(&input.receiver_unit))
    .bind(input.items.len() as i64)
    .bind(numbers_json)
    .execute(&mut *connection)
    .await;

    if let Err(error) = record_result {
        rollback(connection).await;
        if error.to_string().contains("UNIQUE constraint failed") {
            return Err("该扫描单据已经导入过。为防止库存重复增加，本次操作已取消。".into());
        }
        return Err(format!("保存单据导入记录失败，整张单据已回滚：{error}"));
    }

    if let Err(error) = commit(connection).await {
        rollback(connection).await;
        return Err(error);
    }
    Ok(numbers)
}

#[tauri::command]
pub async fn import_scanned_document(
    app: AppHandle,
    input: ScannedDocumentImportInput,
) -> Result<Vec<String>, String> {
    let mut connection = open_connection(&app).await?;
    import_on_connection(&mut connection, &input).await
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn test_connection() -> SqliteConnection {
        let mut connection = SqliteConnection::connect("sqlite::memory:")
            .await
            .expect("open in-memory sqlite");
        configure_connection(&mut connection)
            .await
            .expect("configure sqlite");

        sqlx::query(
            r#"CREATE TABLE inventory_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                location_id INTEGER NOT NULL,
                quantity NUMERIC NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(material_id, location_id)
            )"#,
        )
        .execute(&mut connection)
        .await
        .expect("create balance table");
        sqlx::query(
            r#"CREATE TABLE stock_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_no TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                material_id INTEGER NOT NULL,
                location_id INTEGER NOT NULL,
                quantity NUMERIC NOT NULL,
                occurred_at TEXT NOT NULL,
                related_unit TEXT,
                destination TEXT,
                handler TEXT,
                receiver TEXT,
                remark TEXT,
                created_at TEXT NOT NULL
            )"#,
        )
        .execute(&mut connection)
        .await
        .expect("create transaction table");
        sqlx::query(
            r#"CREATE TABLE document_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_hash TEXT NOT NULL UNIQUE,
                source_file_name TEXT NOT NULL,
                document_type TEXT NOT NULL,
                transfer_basis TEXT,
                supplier_unit TEXT,
                receiver_unit TEXT,
                line_count INTEGER NOT NULL,
                transaction_numbers TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"#,
        )
        .execute(&mut connection)
        .await
        .expect("create import table");
        connection
    }

    fn line(quantity: f64) -> DocumentImportLineInput {
        DocumentImportLineInput {
            material_id: 1,
            location_id: 1,
            quantity,
            occurred_at: "2026-08-17T00:00:00.000Z".into(),
            related_unit: Some("仓库".into()),
            handler: Some("测试员".into()),
            remark: Some("扫描单据导入".into()),
        }
    }

    fn document(items: Vec<DocumentImportLineInput>) -> ScannedDocumentImportInput {
        ScannedDocumentImportInput {
            source_hash: "a".repeat(64),
            source_file_name: "transfer.jpg".into(),
            document_type: "TRANSFER_RECEIVE".into(),
            transfer_basis: Some("2026年计划".into()),
            supplier_unit: Some("仓库".into()),
            receiver_unit: Some("超市".into()),
            items,
        }
    }

    async fn balance(connection: &mut SqliteConnection) -> f64 {
        sqlx::query_scalar::<_, f64>(
            "SELECT CAST(COALESCE(quantity,0) AS REAL) FROM inventory_balances WHERE material_id=1 AND location_id=1",
        )
        .fetch_optional(connection)
        .await
        .expect("read balance")
        .unwrap_or(0.0)
    }

    #[tokio::test]
    async fn document_import_posts_all_lines_and_records_fingerprint_atomically() {
        let mut connection = test_connection().await;
        let numbers = import_on_connection(&mut connection, &document(vec![line(2.0), line(3.0)]))
            .await
            .expect("document import succeeds");

        assert_eq!(numbers.len(), 2);
        assert_eq!(balance(&mut connection).await, 5.0);
        let imports = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM document_imports")
            .fetch_one(&mut connection)
            .await
            .expect("count imports");
        assert_eq!(imports, 1);
    }

    #[tokio::test]
    async fn duplicate_document_is_rejected_without_second_stock_mutation() {
        let mut connection = test_connection().await;
        let input = document(vec![line(4.0)]);
        import_on_connection(&mut connection, &input)
            .await
            .expect("first import succeeds");
        let error = import_on_connection(&mut connection, &input)
            .await
            .expect_err("duplicate must fail");

        assert!(error.contains("已经导入过"));
        assert_eq!(balance(&mut connection).await, 4.0);
        let transactions = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM stock_transactions")
            .fetch_one(&mut connection)
            .await
            .expect("count transactions");
        assert_eq!(transactions, 1);
    }

    #[tokio::test]
    async fn invalid_line_is_rejected_before_any_mutation() {
        let mut connection = test_connection().await;
        let error = import_on_connection(&mut connection, &document(vec![line(2.0), line(0.0)]))
            .await
            .expect_err("invalid row must fail");

        assert!(error.contains("第 2 行"));
        assert_eq!(balance(&mut connection).await, 0.0);
        let imports = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM document_imports")
            .fetch_one(&mut connection)
            .await
            .expect("count imports");
        assert_eq!(imports, 0);
    }
}
