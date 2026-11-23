import assert from 'node:assert/strict'
import { test } from 'node:test'

const workspaceRecents = () => import('../src/utils/workspaceRecents.js')

test('notes-only workspace queries the note model directly', async () => {
  const { loadWorkspaceRecents } = await workspaceRecents()
  const note = { id: 17, entity_type_key: 'note', data: { title: '真实笔记' } }
  const api = {
    getStats() { assert.fail('Mixed statistics can omit older notes') },
    async getEntityTypeByKey(key) {
      assert.equal(key, 'note')
      return { id: 3 }
    },
    async listRecords(typeId, pagination) {
      assert.equal(typeId, 3)
      assert.deepEqual(pagination, { page: 1, page_size: 5 })
      return { items: [note] }
    },
  }
  assert.deepEqual(await loadWorkspaceRecents(api, 'notes'), [{ ...note, record_id: 17 }])
})

test('workspace with a records page uses the recent statistics sample', async () => {
  const { loadWorkspaceRecents } = await workspaceRecents()
  const record = { record_id: 23, entity_type_key: 'customer' }
  const api = {
    async getStats() { return { recent: [record] } },
    getEntityTypeByKey() { assert.fail('The records scope does not require a note lookup') },
  }
  assert.deepEqual(await loadWorkspaceRecents(api, 'records'), [record])
})

test('workspace with neither readable notes nor a records page fetches nothing', async () => {
  const { loadWorkspaceRecents } = await workspaceRecents()
  assert.deepEqual(await loadWorkspaceRecents({}, ''), [])
})
