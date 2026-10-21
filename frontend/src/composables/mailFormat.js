// Формат строки «От» для писем. Жил четырьмя копиями (Mailbox, Mail,
// MailReader ×2 — патч AT), теперь один экземпляр: null-безопасен, чтобы
// читалка могла звать его прямо от computed сообщения.
export function fromLine(item) {
  if (!item) return ""
  if (item.from_name && item.from_addr) return item.from_name + " <" + item.from_addr + ">"
  return item.from_addr || item.from_name || ""
}
