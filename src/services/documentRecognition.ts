import { invoke } from '@tauri-apps/api/core'

export interface RecognizedDocumentLine {
  itemName: string
  specification: string
  quantity: number
  confidence: number
  warnings: string[]
}

export interface RecognizedTransferDocument {
  documentType: 'TRANSFER_RECEIVE'
  transferBasis: string
  supplierUnit: string
  receiverUnit: string
  headerConfidence: number
  lines: RecognizedDocumentLine[]
  warnings: string[]
  ocrEngine: string
  recognizedTextCount: number
}

export async function recognizeTransferDocument(path: string): Promise<RecognizedTransferDocument> {
  const value = path.trim()
  if (!value) throw new Error('请选择扫描图片')
  return invoke<RecognizedTransferDocument>('recognize_transfer_document', { path: value })
}
