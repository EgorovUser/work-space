export function formatSize(bytes) {
  const value = Number(bytes) || 0
  if (value < 1024) return value + " Б"
  if (value < 1024 * 1024) return Math.round(value / 1024) + " КБ"
  return (value / (1024 * 1024)).toFixed(1) + " МБ"
}
