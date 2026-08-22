from aidycai.services.work_items import WorkItemStore


def test_work_item_store_crud(tmp_path):
    store = WorkItemStore(tmp_path / "work_items.json")
    item = store.create("Tarea", "Corregir botón", "Detener proceso", "AIDYC", "Alta")
    assert item.id == 1
    assert store.load()[0].title == "Corregir botón"
    assert store.update_status(1, "Completada")
    assert store.load()[0].status == "Completada"
    assert store.delete(1)
    assert store.load() == []
