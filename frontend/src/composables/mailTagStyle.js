// Стиль пилюли хештега письма: цвет из настройки тега, активный — заливкой.
// Нужен и списку писем (Mailbox), и вкладке хештегов (MailTags) — живёт
// одним экземпляром, чтобы не плодить копии (патч X).
export function tagStyle(tag, active) {
  return {
    color: active ? "#fff" : tag.color,
    borderColor: tag.color,
    background: active ? tag.color : "transparent",
  }
}
