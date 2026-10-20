"""Имена событий — контракт между модулями, не пользовательские настройки."""

from __future__ import annotations

TASK_CREATED = "task.created"
TASK_STATUS_CHANGED = "task.status_changed"
TASK_ASSIGNED = "task.assigned"
TASK_UPDATED = "task.updated"
TASK_DEADLINE_CHANGED = "task.deadline_changed"
TASK_DEADLINE_SOON = "task.deadline_soon"
TASK_OVERDUE = "task.overdue"
TASK_COMMENT = "task.comment"
TASK_DELETED = "task.deleted"
TASK_RECURRED = "task.recurred"
TASK_CHECKLIST_ADDED = "task.checklist_added"
TASK_CHECKLIST_DONE = "task.checklist_done"
TASK_FILE = "task.file"
MAIL_RECEIVED = "mail.received"
MAIL_AUTH_FAILED = "mail.auth_failed"
MAIL_FILED = "mail.filed"
MAIL_EVENT = "mail.event"
MAIL_EVENT_SOON = "mail.event_soon"
MAIL_EVENT_TODAY = "mail.event_today"
MAIL_ARCHIVED = "mail.archived"
MAIL_DELETED = "mail.deleted"
DOC_UPLOADED = "doc.uploaded"
DOC_VERSION = "document.version"
DOC_VERSION_DELETED = "document.version_deleted"
DOC_UPDATED = "document.updated"
DOC_ARCHIVED = "document.archived"
DOC_DELETED = "document.deleted"
EXAMPLE_CREATED = "example.created"
EXAMPLE_UPDATED = "example.updated"
EXAMPLE_FILE = "example.file"
EXAMPLE_DELETED = "example.deleted"
SECRET_CREATED = "secret.created"
SECRET_UPDATED = "secret.updated"
SECRET_DELETED = "secret.deleted"
SECRET_OPENED = "secret.opened"
RDP_CREATED = "rdp.created"
RDP_UPDATED = "rdp.updated"
RDP_DELETED = "rdp.deleted"
TIME_STARTED = "time.started"
TIME_STOPPED = "time.stopped"
TIME_CREATED = "time.created"
TIME_UPDATED = "time.updated"
TIME_DELETED = "time.deleted"
PROJECT_CREATED = "project.created"
PROJECT_UPDATED = "project.updated"
PROJECT_ARCHIVED = "project.archived"
SYSTEM_MODULE_ERROR = "system.module_error"
SYSTEM_STATUS = "system.status"

ALL_EVENTS = (
    TASK_CREATED,
    TASK_STATUS_CHANGED,
    TASK_ASSIGNED,
    TASK_UPDATED,
    TASK_DEADLINE_CHANGED,
    TASK_DEADLINE_SOON,
    TASK_OVERDUE,
    TASK_COMMENT,
    TASK_DELETED,
    TASK_RECURRED,
    TASK_CHECKLIST_ADDED,
    TASK_CHECKLIST_DONE,
    TASK_FILE,
    MAIL_RECEIVED,
    MAIL_AUTH_FAILED,
    MAIL_FILED,
    MAIL_EVENT,
    MAIL_EVENT_SOON,
    MAIL_EVENT_TODAY,
    MAIL_ARCHIVED,
    MAIL_DELETED,
    DOC_UPLOADED,
    DOC_VERSION,
    DOC_VERSION_DELETED,
    DOC_UPDATED,
    DOC_ARCHIVED,
    DOC_DELETED,
    EXAMPLE_CREATED,
    EXAMPLE_UPDATED,
    EXAMPLE_FILE,
    EXAMPLE_DELETED,
    SECRET_CREATED,
    SECRET_UPDATED,
    SECRET_DELETED,
    SECRET_OPENED,
    RDP_CREATED,
    RDP_UPDATED,
    RDP_DELETED,
    TIME_STARTED,
    TIME_STOPPED,
    TIME_CREATED,
    TIME_UPDATED,
    TIME_DELETED,
    PROJECT_CREATED,
    PROJECT_UPDATED,
    PROJECT_ARCHIVED,
    SYSTEM_MODULE_ERROR,
    SYSTEM_STATUS,
)

PENDING = "pending"
PROCESSING = "processing"
DONE = "done"
FAILED = "failed"
