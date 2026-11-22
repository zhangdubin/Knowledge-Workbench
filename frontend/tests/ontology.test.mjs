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
test('multiline quote retains newline and code point offsets', async () => {
  const {readFileSync}=await import('node:fs')
  const source=readFileSync(new URL('../src/views/ontology/IngestionPanel.vue',import.meta.url),'utf8')
  assert.match(source, /<textarea\s+v-model="quote"/)
  assert.deepEqual(quoteRange('前😀行一\n行二','😀行一\n行二'),{start:1,end:7,quote:'😀行一\n行二'})
})
test('opening a missing ingestion source or job immediately clears the confirmed context', async () => {
  const {useIngestionSelection}=await import('../src/views/ontology/useIngestionSelection.js')
  const deny=async()=>{throw Error('403')}
  const state=useIngestionSelection(deny,deny)
  for(const choose of [state.chooseDoc,state.openJob]){
    state.plan.value={id:'old-plan'}; state.job.value={id:'old-job'}; state.doc.value={id:8}
    const pending=choose(9)
    assert.equal(state.plan.value,null)
    assert.equal(state.job.value,null)
    assert.equal(state.doc.value,null)
    await assert.rejects(pending,/403/)
    assert.equal(state.plan.value,null)
  }
})
test('current revision is selected regardless of timestamp ties or history pagination', async () => {
  const {initialRevision}=await import('../src/utils/ontology.js')
  const current={id:'current',status:'published',schema:{types:[],relations:[]}}
  const old={id:'old',status:'published'}
  assert.equal(initialRevision({current_revision_id:'current',revisions:[old,current]}),current)
  assert.deepEqual(initialRevision({current_revision_id:'current',schema:current.schema,revisions:[old]}),current)
  const draft={id:'draft',status:'draft'}
  assert.equal(initialRevision({revisions:[draft]}),draft)
})
test('supersede uses an accepted same-subject/predicate replacement and the reviewed version',async()=>{
  const {eligibleReplacements,reviewBody}=await import('../src/utils/ontology.js')
  const fact={id:'a',predicate_id:'p',object_id:3,status:'accepted',version:4}
  const good={...fact,id:'b'}
  const rows=[fact,good,{...good,id:'c',object_id:4},{...good,id:'d',predicate_id:'q'},{...good,id:'e',status:'candidate'}]
  assert.deepEqual(eligibleReplacements(fact,rows),[good])
  assert.deepEqual(reviewBody('supersede',fact,good.id),{action:'supersede',expected_version:4,superseded_by:'b'})
})
