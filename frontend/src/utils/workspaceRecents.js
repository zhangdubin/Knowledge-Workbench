export async function loadWorkspaceRecents(api, scope) {
  if (scope === 'notes') {
    const noteModel = await api.getEntityTypeByKey('note')
    const { items = [] } = await api.listRecords(noteModel.id, { page: 1, page_size: 5 })
    return items.map(note => ({ ...note, record_id: note.id }))
  }
  if (scope === 'records') {
    const { recent = [] } = await api.getStats()
    return recent
  }
  return []
}
