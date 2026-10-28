/**
 * 笔记分组 API 客户端
 * ---------------------------------------------------------------------------
 * 分组是「知识库」的一等公民：一组笔记可以被自定义分组收纳，
 * 新建笔记时可以直接落到某个分组里。
 *
 * 后端契约：
 *   GET    /api/note-groups            → [{ id, name, color, count, sort_order, ... }]
 *                                          count = 该组下的**笔记（记录形态）**数
 *   POST   /api/note-groups            body {name, color?} → 201；重名 409 {"detail":"分组名已存在"}
 *   PATCH  /api/note-groups/{id}       body {name?, color?, sort_order?} → 分组对象
 *   DELETE /api/note-groups/{id}       → {ok:true}；组内笔记不会被删，只是移出分组；
 *                                          可选 ?move_to=<id>（整组搬到另一个分组）
 *
 * 笔记侧的分组归属存在 record.data.group_id（null / 缺键 = 未分组），
 * 列表接口 GET /api/records?group_id=N 支持服务端过滤（0 = 未分组，不传 = 不过滤）。
 *
 * 纯函数（规整 / 校验 / 错误翻译）放在 components/note/group-utils.js，
 * 那边不依赖 axios，能直接被 node 单测 import。
 *
 * 所有请求都带 silent:true —— 失败由调用方自己处理（分组接口还没上线时
 * 页面要安静降级，而不是弹一串「请求失败」把用户刷屏）。
 */
import api from './index'
import {
  DEFAULT_GROUP_COLOR, GROUP_COLOR_PRESETS, GROUP_NAME_MAX,
  groupErrorMessage, normalizeGroup, normalizeGroups, validateGroupName,
} from '../components/note/group-utils.js'

export {
  DEFAULT_GROUP_COLOR, GROUP_COLOR_PRESETS, GROUP_NAME_MAX,
  groupErrorMessage, normalizeGroup, normalizeGroups, validateGroupName,
}

export const NoteGroupsApi = {
  list: (params = {}) => api.get('/api/note-groups', { params, silent: true }),
  create: (payload) => api.post('/api/note-groups', payload, { silent: true }),
  update: (id, payload) => api.patch(`/api/note-groups/${id}`, payload, { silent: true }),
  remove: (id, moveTo) => api.delete(`/api/note-groups/${id}`, {
    // move_to：删除分组时把组内笔记搬到另一个分组；不传 = 变成「未分组」
    params: moveTo == null ? {} : { move_to: moveTo },
    silent: true,
  }),
}
