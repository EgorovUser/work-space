import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { defineConfig } from "@playwright/test"

// E2E гоняются против настоящего бэкенда (uvicorn) со свежей временной
// базой и собранного фронтенда (dist — его отдаёт само приложение).
// Перед запуском нужен `npm run build`.

const port = process.env.E2E_PORT || "8907"
const baseURL = process.env.E2E_BASE_URL || `http://127.0.0.1:${port}`
// В CI нет .venv — питон ставится setup-python; локально берём из venv репо.
const python = process.env.E2E_PYTHON || ".venv/bin/python"

const dataDir = mkdtempSync(join(tmpdir(), "ws-e2e-"))

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: { baseURL },
  webServer: {
    command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    cwd: "..",
    url: `${baseURL}/healthz`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      APP_ENV: "dev",
      DATA_DIR: dataDir,
      // Явно пустой: иначе внешний DATABASE_URL (например, в песочнице)
      // перебивает путь к временной базе и URL не парсится.
      DATABASE_URL: "",
      SECRET_KEY: "e2e-secret-key",
      // Ключ только для тестовой базы — сгенерирован случайно.
      FERNET_KEY: "dcM-fT5ozgX6Gpboj_F58S9o9XADjuuEyB3859N2Hs8=",
      SEED_USERNAME: "e2e",
      SEED_PASSWORD: "e2e-pass",
      LOG_LEVEL: "ERROR",
    },
  },
})
