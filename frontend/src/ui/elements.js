// Реестр элементов редактируемых страниц (патч AW): имя → компонент.
//
// Контракт: схема свойств (что и чем редактировать) приходит с бэкенда
// из каталога (GET /api/ui/{page} → catalog) — PropertyPanel рендерится
// по ней, как инспектор SurveyJS, который сам является «формой из схемы».
// Здесь — только рендер: новый редактируемый элемент = строка
// defineElement плюс декларация в каталоге бэкенда
// (app/modules/ui/catalog.py), рукописных редакторов не появляется.

const registry = new Map()

export function defineElement(definition) {
  registry.set(definition.name, definition)
}

export function getElement(name) {
  return registry.get(name) || null
}

export function allElements() {
  return [...registry.values()]
}
