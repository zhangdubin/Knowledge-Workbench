import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FLOW_STAGES, flowState, flowSummary } from '../src/utils/operationalFlow.js'

test('知识服务流程按查询状态显示可执行的中文阶段', () => {
  assert.deepEqual(FLOW_STAGES.map(stage => stage.key), ['source', 'scope', 'evidence', 'feedback'])
  assert.deepEqual(flowState({ busy: true, result: null, error: '' }), {
    source: 'done', scope: 'running', evidence: 'pending', feedback: 'pending',
  })
  assert.deepEqual(flowState({ busy: false, result: { status: 'supported' }, error: '' }), {
    source: 'done', scope: 'done', evidence: 'done', feedback: 'ready',
  })
})

test('流程摘要明确说明冲突、不足和失败原因', () => {
  assert.equal(flowSummary({ busy: false, result: { status: 'conflict' }, error: '' }).label, '存在冲突')
  assert.equal(flowSummary({ busy: false, result: { status: 'insufficient' }, error: '' }).label, '信息不足')
  assert.equal(flowSummary({ busy: false, result: null, error: '接口不可用' }).label, '检索失败')
})
