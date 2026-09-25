<template>
  <div class="not-found">
    <div class="nf-icon">🛰️</div>
    <h1>404</h1>
    <p>页面去漫游宇宙了 · 找不到这条路径</p>
    <p class="path">/{{ $route.path }}</p>
    <el-button type="primary" size="large" @click="$router.push('/')">
      <el-icon><HomeFilled /></el-icon>回到工作台
    </el-button>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  text-align: center;
  gap: 12px;
}
.nf-icon {
  font-size: 60px;
  opacity: 0.5;
  animation: float 3s ease-in-out infinite;
}
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}
h1 {
  font-size: 92px;
  font-weight: 700;
  letter-spacing: -3px;
  background: linear-gradient(150deg, #6a6ed4 0%, #474bb0 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0;
  line-height: 1;
}
p {
  color: var(--text-secondary);
  margin: 4px 0;
}
.path {
  color: var(--text-tertiary);
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 13px;
}
</style>