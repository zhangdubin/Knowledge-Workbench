import test from 'node:test'
import assert from 'node:assert/strict'
import {
  sampleSchema,
  validateSchema,
  quoteRange,
  versionedData,
  confirmBody,
  reviewBody,
} from '../src/utils/ontology.js'

test('saved identities survive label, key and order changes', () => {
  const schema = sampleSchema()
  const [a, b] = schema.types
  a.key = 'renamed'
  schema.types.reverse()
  assert.equal(schema.relations[0].source, a.id)
  assert.equal(schema.relations[0].target, b.id)
  assert.doesNotThrow(() => validateSchema(schema))
  a.fields.push({ ...a.fields[0] })
  assert.throws(() => validateSchema(schema), /重复/)
  a.fields.pop()
  a.fields[0].type = 'invented'
  assert.throws(() => validateSchema(schema), /类型/)
  a.fields[0].type = 'text'
  schema.relations[0].cardinality = 'invented'
  assert.throws(() => validateSchema(schema), /基数/)
})
test('exact quote selects a specified occurrence after supplementary characters', () => {
  assert.deepEqual(quoteRange('😀证据：证据', '证据', 2), { start: 4, end: 6, quote: '证据' })
  assert.throws(() => quoteRange('abc', 'b', 2))
})
test('writes keep the read version and only submit server-issued confirmation identity', () => {
  assert.deepEqual(versionedData({ x: 2 }, 3), { data: { x: 2 }, expected_version: 3 })
  assert.deepEqual(versionedData({ x: 2 }), { data: { x: 2 } })
  assert.deepEqual(confirmBody({ change_id: 'plan', args: { x: 2 } }), { change_id: 'plan' })
  assert.deepEqual(reviewBody('accept', { version: 4, args: {} }), {
    action: 'accept',
    expected_version: 4,
  })
})
test('the editable copy uses server-assigned field identities on the next save', async () => {
  const { draftSchema } = await import('../src/utils/ontology.js')
  const saved = {
    schema: {
      types: [{ id: 't', key: 'topic', fields: [{ id: 'property', key: 'name', type: 'text' }] }],
      relations: [],
    },
  }
  const next = draftSchema(saved)
  next.types[0].fields[0].key = 'title'
  assert.equal(next.types[0].fields[0].id, 'property')
  assert.equal(saved.schema.types[0].fields[0].key, 'name')
})
test('publication impact summary reports each real affected count', async () => {
  const { impactSummary } = await import('../src/utils/ontology.js')
  assert.equal(
    impactSummary({ counts: { types: 2, records: 11, relations: 0 } }),
    '涉及 2 个类型、11 条记录、0 条关联',
  )
})
