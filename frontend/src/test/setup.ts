// Newer Node versions expose an experimental `localStorage` getter that shadows happy-dom's implementation
// and yields undefined without --localstorage-file; install an in-memory replacement in that case.
if (typeof globalThis.localStorage === 'undefined' || typeof globalThis.localStorage?.clear !== 'function') {
  const data = new Map<string, string>()
  const storage: Storage = {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => {
      data.delete(key)
    },
    setItem: (key, value) => {
      data.set(key, String(value))
    },
  }
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true })
}
