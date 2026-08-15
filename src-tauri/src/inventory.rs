use serde::Deserialize;
use sqlx::{Connection, Executor, SqliteConnection};
use std::{fs, path::PathBuf};
use tauri::{AppHandle, Manager};
use uuid::Uuid;

const DATABASE_FILE: &str = "kylin-stock.db";

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StockOperationInput {
    material_id: i64,
    location_id: i64,
    quantity: f64,
    occurred_at: String,
    related_unit: Option<String>,
    destination: Option<String>,
    handler: Option<String>,
    receiver: Option<String>,
    remark: Option<String>,
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

    sqlx::query("PRAGMA foreign_keys = ON")
        .execute(&mut connection)
        .await
        .map_err(|e| format!("无法启用数据库外键约束：{e}"))?;
    sqlx::query("PRAGMA busy_timeout = 5000")
        .execute(&mut connection)
        .await
        .map_err(|e| format!("无法设置数据库等待策略：{e}"))?;

    Ok(connection)
}

fn validate(input: &StockOperationInput) -> Result<(), String> {
    if input.material_id <= 0 {
        return Err("请选择物资".into());
    }
    if input.location_id <= 0 {
        return Err("请选择存放位置".into());
    }
    if !input.quantity.is_finite() || input.quantity <= 0.0 {
        return Err("数量必须大于 0".into());
    }
    if input.occurred_at.trim().is_empty() {
        return Err("请选择业务时间".into());
    }
    Ok(())
}

fn clean(value: &Option<String>) -> Option<String> {
    value
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn transaction_no(kind: &str) -> String {
    format!("{}-{}", kind, Uuid::new_v4().simple())
}

async fn begin_immediate(connection: &mut SqliteConnection) -> Result<(), String> {
    sqlx::query("BEGIN IMMEDIATE")
        .execute(connection)
        .await
        .map(|_| ())
        .map_err(|e| format!("无法开始库存事务：{e}"))
}

async fn rollback(connection: &mut SqliteConnection) {
    let _ = sqlx::query("ROLLBACK").execute(connection).await;
}

async fn commit(connection: &mut SqliteConnection) -> Result<(), String> {
    sqlx::query("COMMIT")
        .execute(connection)
        .await
        .map(|_| ())
        .map_err(|e| format!("库存事务提交失败：{e}"))
}

#[tauri::command]
pub async fn stock_in(app: AppHandle, input: StockOperationInput) -> Result<String, String> {
    validate(&input)?;
    let mut connection = open_connection(&app).await?;
    begin_immediate(&mut connection).await?;

    let transaction_no = transaction_no("IN");
    let result: Result<(), String> = async {
        sqlx::query(
            r#"INSERT INTO stock_transactions
              (transaction_no,type,material_id,location_id,quantity,occurred_at,related_unit,destination,handler,receiver,remark,created_at)
              VALUES (?,'IN',?,?,?,?,?,NULL,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))"#,
        )
        .bind(&transaction_no)
        .bind(input.material_id)
        .bind(input.location_id)
        .bind(input.quantity)
        .bind(input.occurred_at.trim())
        .bind(clean(&input.related_unit))
        .bind(clean(&input.handler))
        .bind(clean(&input.receiver))
        .bind(clean(&input.remark))
        .execute(&mut connection)
        .await
        .map_err(|e| e.to_string())?;

        sqlx::query(
            r#"INSERT INTO inventory_balances(material_id,location_id,quantity,updated_at)
               VALUES (?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
               ON CONFLICT(material_id,location_id) DO UPDATE SET
               quantity = quantity + excluded.quantity,
               updated_at = excluded.updated_at"#,
        )
        .bind(input.material_id)
        .bind(input.location_id)
        .bind(input.quantity)
        .execute(&mut connection)
        .await
        .map_err(|e| e.to_string())?;

        Ok(())
    }
    .await;

    if let Err(error) = result {
        rollback(&mut connection).await;
        return Err(format!("入库登记失败：{error}"));
    }
    if let Err(error) = commit(&mut connection).await {
        rollback(&mut connection).await;
        return Err(error);
    }

    Ok(transaction_no)
}

#[tauri::command]
pub async fn stock_out(app: AppHandle, input: StockOperationInput) -> Result<String, String> {
    validate(&input)?;
    let destination = clean(&input.destination).ok_or_else(|| "出库去向不能为空".to_string())?;

    let mut connection = open_connection(&app).await?;
    begin_immediate(&mut connection).await?;

    let available = match sqlx::query_scalar::<_, f64>(
        "SELECT quantity FROM inventory_balances WHERE material_id=? AND location_id=?",
    )
    .bind(input.material_id)
    .bind(input.location_id)
    .fetch_optional(&mut connection)
    .await
    {
        Ok(value) => value.unwrap_or(0.0),
        Err(error) => {
            rollback(&mut connection).await;
            return Err(format!("读取当前库存失败：{error}"));
        }
    };

    if available + f64::EPSILON < input.quantity {
        rollback(&mut connection).await;
        return Err(format!("库存不足，当前可用库存为 {available}"));
    }

    let transaction_no = transaction_no("OUT");
    let result: Result<(), String> = async {
        sqlx::query(
            r#"INSERT INTO stock_transactions
              (transaction_no,type,material_id,location_id,quantity,occurred_at,related_unit,destination,handler,receiver,remark,created_at)
              VALUES (?,'OUT',?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))"#,
        )
        .bind(&transaction_no)
        .bind(input.material_id)
        .bind(input.location_id)
        .bind(input.quantity)
        .bind(input.occurred_at.trim())
        .bind(clean(&input.related_unit))
        .bind(&destination)
        .bind(clean(&input.handler))
        .bind(clean(&input.receiver))
        .bind(clean(&input.remark))
        .execute(&mut connection)
        .await
        .map_err(|e| e.to_string())?;

        let update = sqlx::query(
            r#"UPDATE inventory_balances
               SET quantity = quantity - ?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE material_id=? AND location_id=? AND quantity >= ?"#,
        )
        .bind(input.quantity)
        .bind(input.material_id)
        .bind(input.location_id)
        .bind(input.quantity)
        .execute(&mut connection)
        .await
        .map_err(|e| e.to_string())?;

        if update.rows_affected() != 1 {
            return Err("库存余额发生变化，本次出库已取消，请重试".into());
        }

        Ok(())
    }
    .await;

    if let Err(error) = result {
        rollback(&mut connection).await;
        return Err(format!("出库登记失败：{error}"));
    }
    if let Err(error) = commit(&mut connection).await {
        rollback(&mut connection).await;
        return Err(error);
    }

    Ok(transaction_no)
}
