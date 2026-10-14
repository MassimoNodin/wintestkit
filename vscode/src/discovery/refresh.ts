interface Entry {
  revision: number;
  running: boolean;
  timer?: ReturnType<typeof setTimeout>;
}

export class LatestRefresh<Result> {
  private readonly entries = new Map<string, Entry>();
  private disposed = false;
  constructor(
    private readonly load: (key: string) => Promise<Result>,
    private readonly apply: (key: string, result: Result) => void,
    private readonly error: (error: unknown) => void,
  ) {}
  schedule(key: string, delay = 0): void {
    if (this.disposed) return;
    const entry = this.entries.get(key) ?? { revision: 0, running: false };
    this.entries.set(key, entry);
    entry.revision++;
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = undefined;
    if (delay)
      entry.timer = setTimeout(() => {
        entry.timer = undefined;
        void this.flush(key, entry);
      }, delay);
    else void this.flush(key, entry);
  }
  private async flush(key: string, entry: Entry): Promise<void> {
    if (entry.running || this.disposed || this.entries.get(key) !== entry)
      return;
    entry.running = true;
    try {
      while (!this.disposed && this.entries.get(key) === entry) {
        const revision = entry.revision;
        try {
          const result = await this.load(key);
          if (
            !this.disposed &&
            this.entries.get(key) === entry &&
            revision === entry.revision
          )
            this.apply(key, result);
        } catch (error) {
          if (!this.disposed) this.error(error);
        }
        if (revision === entry.revision || entry.timer) break;
      }
    } finally {
      entry.running = false;
    }
  }
  remove(key: string): void {
    const entry = this.entries.get(key);
    if (entry?.timer) clearTimeout(entry.timer);
    this.entries.delete(key);
  }
  dispose(): void {
    this.disposed = true;
    for (const key of this.entries.keys()) this.remove(key);
  }
}
