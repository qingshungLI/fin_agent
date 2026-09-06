declare module "parquetjs-lite" {
  interface ParquetReader { getCursor(): { next(): Promise<Record<string, unknown> | null> }; close(): Promise<void>; }
  export const ParquetReader: { openFile(path: string): Promise<ParquetReader> };
}
