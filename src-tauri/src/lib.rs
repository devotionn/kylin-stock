mod backup;
mod document_import;
mod inventory;
mod migration;
mod ocr;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_sql::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            backup::create_database_backup,
            backup::restore_database_backup,
            document_import::import_scanned_document,
            inventory::stock_in,
            inventory::batch_stock_in,
            inventory::stock_out,
            migration::initialize_database_schema,
            ocr::recognize_transfer_document
        ])
        .run(tauri::generate_context!())
        .expect("error while running KylinStock");
}