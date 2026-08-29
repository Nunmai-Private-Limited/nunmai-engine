export function logError(error: unknown): void {
  if (!process.env.NUNMAI_INK_DEBUG_ERRORS) {
    return
  }

  console.error(error)
}
