/**
 * 养料库的「学习与产出」接口
 *
 * 为什么单独一个文件：api/index.js 里是全站共用的一批接口，
 * 那边改动频繁（多人并行），把新接口塞进去容易撞车。
 * 这里只放本次新增的一组：评分、可复用产出、外部开源项目。
 *
 * 用法与 index.js 一致：import { DnaLearn } from '../api/dnaLearn'
 */
import api from './index'

export const DnaLearn = {
  // ---- 评分 ----
  /** 单条基因的评分明细（分数 + 分项 + 依据） */
  geneScore: (id) => api.get(`/api/dna/library/genes/${id}/score`),
  /** 人工纠正一条基因（负反馈，会真的扣分） */
  correctGene: (id, note) =>
    api.post(`/api/dna/library/genes/${id}/correct`, { note: note || '' }),
  /** 重算评分（不给 gene_ids 就是全量回填） */
  rescore: (payload) => api.post('/api/dna/library/score/rescore', payload || {}),

  // ---- 可复用产出（学以致用）----
  assets: (params) => api.get('/api/dna/library/assets', { params }),
  assetStats: () => api.get('/api/dna/library/assets/stats'),
  assetUses: (params) => api.get('/api/dna/library/assets/uses', { params }),
  /** 从高分基因里落出可复用产出 */
  assetsFromGenes: (payload) =>
    api.post('/api/dna/library/assets/from-genes', payload || {}),
  /** 记录一次「资产被用了」—— 闭环的关键一步 */
  useAsset: (id, payload) =>
    api.post(`/api/dna/library/assets/${id}/use`, payload || {}),

  // ---- 外部开源项目（openkb 类）----
  /** 导入前预检：认不认得这个仓库、许可证是什么、合规提示是什么 */
  openkbPreview: (params) => api.get('/api/dna/library/openkb/preview', { params }),
  /** 吸收一个外部开源项目（GitHub 或本地镜像） */
  openkbImport: (payload) => api.post('/api/dna/library/openkb/import', payload || {}),
  openkbSources: (params) => api.get('/api/dna/library/openkb/sources', { params }),
  openkbSource: (id) => api.get(`/api/dna/library/openkb/sources/${id}`),
}

export default DnaLearn
