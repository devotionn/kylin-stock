import { invoke } from '@tauri-apps/api/core'
import { withDatabaseMutation } from './database'

export interface RecognizedDocumentLine {
  itemName: string
  specification: string
  quantity: number
  confidence: number
  warnings: string[]
}

export interface RecognizedTransferDocument {
  documentType: 'TRANSFER_RECEIVE'
  sourceSha256: string
  transferBasis: string
  supplierUnit: string
  receiverUnit: string
  headerConfidence: number
  lines: RecognizedDocumentLine[]
  warnings: string[]
  ocrEngine: string
  recognizedTextCount: number
}

export interface ScannedDocumentImportLine {
  materialId: number
  locationId: number
  quantity: number
  occurredAt: string
  relatedUnit?: string
  handler?: string
  remark?: string
}

export interface ScannedDocumentImportInput {
  sourceHash: string
  sourceFileName: string
  documentType: 'TRANSFER_RECEIVE'
  transferBasis?: string
  supplierUnit?: string
  receiverUnit?: string
  items: ScannedDocumentImportLine[]
}

export async function recognizeTransferDocument(path: string): Promise<RecognizedTransferDocument> {
  const value = path.trim()
  if (!value) throw new Error('请选择扫描图片')
  return invoke<RecognizedTransferDocument>('recognize_transfer_document', { path: value })
}

export async function importScannedDocument(input: ScannedDocumentImportInput): Promise<string[]> {
  if (!input.sourceHash || input.sourceHash.length !== 64) throw new Error('单据指纹无效，请重新识别')
  if (!input.items.length) throw new Error('至少需要一条物资明细')
  return withDatabaseMutation(() => invoke<string[]>('import_scanned_document', { input }))
}
