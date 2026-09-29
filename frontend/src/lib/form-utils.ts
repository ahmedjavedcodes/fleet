// react-hook-form gives "" for an untouched optional text/date input, which the
// backend would either store as an empty string or reject (dates). Optional
// fields register with this so a blank input means "not provided".
export function emptyToUndefined<T>(value: T | "" | null | undefined): T | undefined {
  return value === "" || value === null || value === undefined ? undefined : value
}

// Same, for optional number inputs (valueAsNumber yields NaN when blank).
export function blankNumberToUndefined(value: unknown): number | undefined {
  return value === "" || value === null || value === undefined || Number.isNaN(value) ? undefined : (value as number)
}
