use serde::{Deserialize, Serialize};
use std::{
    env,
    fs,
    path::{Path, PathBuf},
    process::Command,
};
use tauri::{AppHandle, Manager};

const MAX_IMAGE_BYTES: u64 = 30 * 1024 * 1024;
const MAX_WORKER_OUTPUT_BYTES: usize = 2 * 1024 * 1024;
const ALLOWED_EXTENSIONS: &[&str] = &["jpg", "jpeg", "png", "bmp", "tif", "tiff"];

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecognizedLine {
    pub item_name: String,
    pub specification: String,
    pub quantity: f64,
    pub confidence: f64,
    #[serde(default)]
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecognizedTransferDocument {
    pub document_type: String,
    pub source_sha256: String,
    pub transfer_basis: String,
    pub supplier_unit: String,
    pub receiver_unit: String,
    pub header_confidence: f64,
    pub lines: Vec<RecognizedLine>,
    #[serde(default)]
    pub warnings: Vec<String>,
    pub ocr_engine: String,
    pub recognized_text_count: usize,
}

fn validate_image(path: &Path) -> Result<PathBuf, String> {
    let metadata = fs::metadata(path).map_err(|_| "所选扫描图片不存在或无法读取".to_string())?;
    if !metadata.is_file() {
        return Err("请选择一个扫描图片文件".into());
    }
    if metadata.len() == 0 {
        return Err("扫描图片为空文件".into());
    }
    if metadata.len() > MAX_IMAGE_BYTES {
        return Err("扫描图片超过 30MB，请先压缩或重新扫描".into());
    }

    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !ALLOWED_EXTENSIONS.contains(&extension.as_str()) {
        return Err("仅支持 JPG、PNG、BMP、TIF/TIFF 扫描图片".into());
    }

    path.canonicalize()
        .map_err(|e| format!("无法解析扫描图片路径：{e}"))
}

fn find_worker(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(override_path) = env::var("KYLIN_STOCK_OCR_WORKER") {
        let path = PathBuf::from(override_path);
        if path.is_file() {
            return Ok(path);
        }
        return Err("KYLIN_STOCK_OCR_WORKER 指向的脚本不存在".into());
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("无法定位应用资源目录：{e}"))?;
    let candidates = [
        resource_dir.join("resources").join("ocr_worker.py"),
        resource_dir.join("ocr_worker.py"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources")
            .join("ocr_worker.py"),
    ];
    candidates
        .into_iter()
        .find(|candidate| candidate.is_file())
        .ok_or_else(|| "OCR worker 未随应用安装，请重新安装完整程序".to_string())
}

fn python_executable() -> String {
    env::var("KYLIN_STOCK_OCR_PYTHON").unwrap_or_else(|_| {
        if cfg!(target_os = "windows") {
            "python".into()
        } else {
            "python3".into()
        }
    })
}

fn truncate_stderr(bytes: &[u8]) -> String {
    let text = String::from_utf8_lossy(bytes).trim().to_string();
    const LIMIT: usize = 4_000;
    if text.chars().count() <= LIMIT {
        return text;
    }
    let shortened: String = text.chars().take(LIMIT).collect();
    format!("{shortened}…")
}

fn run_worker(worker: PathBuf, image: PathBuf) -> Result<RecognizedTransferDocument, String> {
    let python = python_executable();
    let output = Command::new(&python)
        .arg(&worker)
        .arg(&image)
        .env("PYTHONUNBUFFERED", "1")
        .output()
        .map_err(|e| {
            format!(
                "无法启动本地 OCR 环境（{python}）：{e}。请安装 Python OCR 运行环境，或设置 KYLIN_STOCK_OCR_PYTHON。"
            )
        })?;

    if !output.status.success() {
        let detail = truncate_stderr(&output.stderr);
        return Err(if detail.is_empty() {
            format!("OCR worker 执行失败，退出码 {:?}", output.status.code())
        } else {
            detail
        });
    }
    if output.stdout.len() > MAX_WORKER_OUTPUT_BYTES {
        return Err("OCR 返回数据异常过大，本次识别已取消".into());
    }

    serde_json::from_slice::<RecognizedTransferDocument>(&output.stdout)
        .map_err(|e| format!("OCR 返回数据格式无效：{e}"))
}

#[tauri::command]
pub async fn recognize_transfer_document(
    app: AppHandle,
    path: String,
) -> Result<RecognizedTransferDocument, String> {
    let image = validate_image(Path::new(path.trim()))?;
    let worker = find_worker(&app)?;

    tauri::async_runtime::spawn_blocking(move || run_worker(worker, image))
        .await
        .map_err(|e| format!("OCR 后台任务异常终止：{e}"))?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_worker_contract() {
        let json = r#"{
          "documentType":"TRANSFER_RECEIVE",
          "sourceSha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
          "transferBasis":"2026年计划",
          "supplierUnit":"仓库",
          "receiverUnit":"超市",
          "headerConfidence":0.98,
          "lines":[{
            "itemName":"粉笔",
            "specification":"10.9型粉笔",
            "quantity":1000,
            "confidence":0.97,
            "warnings":[]
          }],
          "warnings":[],
          "ocrEngine":"RapidOCR/ONNX Runtime",
          "recognizedTextCount":42
        }"#;
        let result: RecognizedTransferDocument = serde_json::from_str(json).expect("parse worker output");
        assert_eq!(result.document_type, "TRANSFER_RECEIVE");
        assert_eq!(result.source_sha256.len(), 64);
        assert_eq!(result.lines.len(), 1);
        assert_eq!(result.lines[0].quantity, 1000.0);
    }

    #[test]
    fn rejects_non_image_extension_before_ocr() {
        let path = env::temp_dir().join(format!("kylin-stock-ocr-{}.txt", uuid::Uuid::new_v4()));
        fs::write(&path, b"not an image").expect("write temporary file");
        let error = validate_image(&path).expect_err("non-image must fail");
        let _ = fs::remove_file(&path);
        assert!(error.contains("仅支持"));
    }
}