import assert from 'node:assert/strict'
import { register } from 'node:module'
import { test } from 'node:test'

const apiStub = 'data:text/javascript,' + encodeURIComponent('export const Api = {}')
register('data:text/javascript,' + encodeURIComponent(`
  export async function resolve(specifier, context, nextResolve) {
    if (specifier === '../api') return { url: '${apiStub}', shortCircuit: true, format: 'module' }
    return nextResolve(specifier, context)
  }
`), import.meta.url)

const { permForPath } = await import('../src/composables/useNavItems.js')
const loadWorkspace = () => import('../src/utils/workspaceNavigation.js')
const allowAll = () => true
const allPaths = (navigation) => navigation.groups.flatMap(group => group.items.map(item => item.path))

test('the catalog keeps every legacy destination and up to five primary destinations', async () => {
  const { getWorkspaceNavigation } = await loadWorkspace()
  const navigation = getWorkspaceNavigation({ canPage: allowAll, canFeature: allowAll })
  assert.deepEqual(navigation.primary.map(item => item.path), ['/', '/knowledge-service', '/library', '/notes', '/apps', '/ontology', '/knowledge/graph'])
  assert.deepEqual(allPaths(navigation).sort(), [
    '/', '/ai-settings', '/apps', '/dashboards', '/dev', '/dna', '/dna-library', '/graph', '/guide',
    '/knowledge/graph', '/knowledge-service', '/library', '/notes', '/relations', '/search', '/system/audit',
    '/system/nav', '/system/recycle', '/system/roles', '/system/settings', '/system/storage',
    '/system/users', '/types', '/ontology',
  ].sort())
})

test('page and feature permissions apply to both built-in and custom destinations', async () => {
  const { getWorkspaceNavigation, searchWorkspaceCommands } = await loadWorkspace()
  const navigation = getWorkspaceNavigation({
    canPage: permission => ['notes', 'system'].includes(permission),
    canFeature: () => false,
    customItems: [
      { path: '/system/storage?tab=backup', label: '存储快捷方式' },
      { path: '/SYSTEM/USERS/#details', label: '用户快捷方式' },
      { path: '/dna-library/run', label: '养料快捷方式' },
      { path: '/records/12', label: '记录快捷方式' },
      { path: '/apps/example', label: '业务快捷方式' },
      { path: '/notes/12', label: '我的笔记' },
    ],
  })
  assert.deepEqual(navigation.primary.map(item => item.path), ['/notes'])
  assert.deepEqual(allPaths(navigation).sort(), ['/notes', '/notes/12'])
  assert.deepEqual(navigation.shortcuts.map(item => item.path), ['/notes/12'])
  assert.deepEqual(searchWorkspaceCommands(navigation.groups, '存储'), [])
})

test('path permissions cover routed descendants and ignore similarly named paths', () => {
  for (const [path, permission] of [
    ['/ontology','types'], ['/dna', 'dna'], ['/dna-library', 'dna'], ['/dna-library/details', 'dna'],
    ['/knowledge/graph/', 'knowledge_graph'], ['/dashboards/2', 'dashboards'],
    ['/dev/settings', 'dev'], ['/system/nav', 'system'], ['/records/12?id=7', 'records'],
    ['/notes-fake', ''], ['/appshelf', ''], ['/library-files', ''], ['/system-help', ''],
    ['/notes/../records/12', 'records'], ['/DNA-LIBRARY/?a=b', 'dna'],
  ]) {
    assert.equal(permForPath(path), permission, path)
  }
})

test('custom destinations are deduplicated and stay discoverable beyond three shortcuts', async () => {
  const { getWorkspaceNavigation } = await loadWorkspace()
  const navigation = getWorkspaceNavigation({
    canPage: allowAll,
    canFeature: allowAll,
    customItems: [
      { path: '/notes', label: '内置路由的副本' },
      { path: '/mine', label: '第一条' },
      { path: '/mine', label: '重复项' },
      { path: '/mine/', label: '重复项' },
      { path: '/two', label: '第二条' },
      { path: '/three', label: '第三条' },
      { path: '/four', label: '第四条' },
    ],
  })
  assert.deepEqual(navigation.shortcuts.map(item => item.path), ['/mine', '/two', '/three'])
  assert.equal(navigation.groups.flatMap(group => group.items).find(item => item.path === '/mine').label, '第一条')
  assert.equal(allPaths(navigation).filter(path => path === '/notes').length, 1)
  assert.ok(allPaths(navigation).includes('/four'))
  assert.ok(!allPaths(navigation).includes('/mine/'))
})

test('app shortcut identity preserves key case and deduplicates static casing and trailing slashes', async () => {
  const { getWorkspaceNavigation, searchWorkspaceCommands } = await loadWorkspace()
  const navigation = getWorkspaceNavigation({
    canPage: permission => permission === 'apps',
    canFeature: () => false,
    customItems: [
      { path: '/apps/CRM', label: 'CRM 团队' },
      { path: '/apps/crm', label: 'CRM 业务' },
      { path: '/APPS/CRM/', label: 'CRM 团队的重复项' },
    ],
  })
  const expected = ['/apps/CRM', '/apps/crm']
  assert.deepEqual(navigation.shortcuts.map(item => item.path), expected)
  assert.deepEqual(searchWorkspaceCommands(navigation.groups, '/apps/crm').map(item => item.path), expected)
  assert.equal(permForPath('/APPS/CRM/'), 'apps')
})

test('command search matches trimmed Chinese, case-insensitive paths and descriptions', async () => {
  const { getWorkspaceNavigation, searchWorkspaceCommands } = await loadWorkspace()
  const { groups } = getWorkspaceNavigation({ canPage: allowAll, canFeature: allowAll })
  for (const [query, path] of [
    ['  知识笔记　', '/notes'], ['/LIBRARY', '/library'], ['知识库', '/notes'],
  ]) {
    assert.ok(searchWorkspaceCommands(groups, query).some(item => item.path === path), query)
  }
  assert.deepEqual(searchWorkspaceCommands(groups, '  无匹配示例  '), [])
})

test('nested active state matches full path segments and the graph has a gated fallback', async () => {
  const { activeWorkspacePath, getWorkspaceNavigation } = await loadWorkspace()
  const navigation = getWorkspaceNavigation({
    canPage: permission => ['dashboard', 'notes', 'graph'].includes(permission),
    canFeature: () => false,
  })
  assert.deepEqual(navigation.primary.map(item => item.path), ['/', '/notes', '/graph'])
  assert.equal(activeWorkspacePath('/notes/12', navigation.primary), '/notes')
  assert.equal(activeWorkspacePath('/notes-fake', navigation.primary), '')
  assert.equal(activeWorkspacePath('/knowledge/graph', navigation.primary), '')
  assert.equal(activeWorkspacePath('/system/settings', navigation.primary), '')
  assert.equal(activeWorkspacePath('/', navigation.primary), '/')
})
