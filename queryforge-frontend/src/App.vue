<template>
  <div class="chat-page">
    <Transition name="toast">
      <div
        v-if="notice"
        class="export-toast"
        :class="`export-toast-${notice.type}`"
        role="status"
        aria-live="polite"
      >
        {{ notice.text }}
      </div>
    </Transition>

    <!-- 消息区 -->
    <div ref="messagesEl" class="messages">
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :class="['message-row', msg.role]"
      >
        <div v-if="msg.role === 'assistant'" class="avatar">🤖</div>

        <div class="bubble" :class="{ 'bubble-data': msg.type === 'table' }">
          <!-- 文本 -->
          <div v-if="msg.type === 'text'">
            {{ msg.content }}
          </div>

          <!-- 步骤 -->
          <div v-else-if="msg.type === 'steps'" class="steps">
            <div v-for="(step, sIdx) in msg.steps" :key="sIdx" class="step">
              <span class="dot" :class="step.status"></span>
              <span>{{ step.text }}</span>
            </div>
          </div>

          <!-- 表格 -->
          <div v-else-if="msg.type === 'table'" class="table-wrap">
            <ChartView v-if="msg.chart" :chart="msg.chart" :rows="msg.rows" />
            <table class="result-table">
              <thead>
                <tr>
                  <th v-for="col in msg.columns" :key="col">
                    {{ col }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, rIdx) in msg.rows" :key="rIdx">
                  <td v-for="col in msg.columns" :key="col">
                    {{ row[col] }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 错误 -->
          <div v-else-if="msg.type === 'error'" class="error-text">
            <div class="error-title">{{ msg.content }}</div>
            <div v-if="msg.detail" class="error-detail">
              <span class="error-detail-toggle" @click="msg.showDetail = !msg.showDetail">
                {{ msg.showDetail ? "收起错误详情 ▲" : "查看错误详情 ▼" }}
              </span>
              <pre v-if="msg.showDetail" class="error-detail-body">{{ msg.detail }}</pre>
            </div>
          </div>
        </div>

        <div v-if="msg.role === 'user'" class="avatar">🧑</div>
      </div>
      <div class="messages-bottom-spacer"></div>
    </div>

    <!-- 悬浮输入框 -->
    <div class="input-wrapper">
      <div class="input-box">
        <input
          v-model="question"
          @keyup.enter="sendQuestion"
          placeholder="请输入你的问题..."
        />
        <button @click="sendQuestion" :disabled="loading">
          {{ loading ? "执行中..." : "发送" }}
        </button>
        <button
          class="export-btn"
          @click="exportLatestReply"
          :disabled="loading || exporting || latestReply.type === 'none'"
        >
          {{ exporting ? "导出中..." : "导出最近结果" }}
        </button>
        <button class="new-chat-btn" @click="newChat" :disabled="loading">新对话</button>
        <button class="delete-chat-btn" @click="clearAllChats" :disabled="loading">清空聊天记录</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref } from "vue";
import ChartView from "./components/ChartView.vue";
import { exportTableToExcel } from "./utils/exportExcel.js";

const API_URL = "/api/query";
const SESSION_KEY = "queryforge_session_id";

const question = ref("");
const loading = ref(false);
const exporting = ref(false);
const messages = ref([]);
const messagesEl = ref(null);
const latestReply = ref({ type: "none", query: "", columns: [], rows: [] });
const notice = ref(null);
let noticeTimer = null;

function resetLatestReply() {
  latestReply.value = { type: "none", query: "", columns: [], rows: [] };
}

function showNotice(text, type = "info") {
  notice.value = { text, type };
  if (noticeTimer) window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => {
    notice.value = null;
    noticeTimer = null;
  }, 3200);
}

async function exportLatestReply() {
  if (loading.value || exporting.value || latestReply.value.type === "none") return;

  exporting.value = true;
  try {
    const reply = latestReply.value;
    const hasTableData = reply.type === "query" && reply.rows.length > 0;

    await exportTableToExcel({
      columns: hasTableData ? reply.columns : [],
      rows: hasTableData ? reply.rows : [],
    });

    if (reply.type === "non_query") {
      showNotice("最近一次回复不是数据查询，已导出空白 Excel 文件", "warning");
    } else if (reply.type === "error") {
      showNotice("最近一次查询未产生表格数据，已导出空白 Excel 文件", "warning");
    } else if (!reply.rows.length) {
      showNotice("最近一次查询结果为空，已导出空白 Excel 文件", "warning");
    } else {
      showNotice(`已导出最近一次查询的 ${reply.rows.length} 行表格数据`, "success");
    }
  } catch (error) {
    showNotice(`Excel 导出失败：${error?.message || "未知错误"}`, "error");
  } finally {
    exporting.value = false;
  }
}

onBeforeUnmount(() => {
  if (noticeTimer) window.clearTimeout(noticeTimer);
});

// 会话 id:localStorage 持久化,实现跨刷新多轮记忆;「新对话」清空后重新生成
function getSessionId() {
  return localStorage.getItem(SESSION_KEY) || "";
}

function saveSessionId(sid) {
  localStorage.setItem(SESSION_KEY, sid);
}

function newChat() {
  if (loading.value) return;
  localStorage.removeItem(SESSION_KEY);
  messages.value = [];
  resetLatestReply();
}

// 清空聊天记录:调用后端删除 Redis 中所有会话历史,再清空本地会话与消息
async function clearAllChats() {
  if (loading.value) return;
  if (!window.confirm("确定清空所有聊天记录吗？此操作会清除服务器端全部会话记忆。")) return;
  try {
    const resp = await fetch("/api/sessions", { method: "DELETE" });
    if (!resp.ok) throw new Error(`清空失败: ${resp.status}`);
    localStorage.removeItem(SESSION_KEY);
    messages.value = [];
    resetLatestReply();
  } catch (e) {
    alert("清空失败，请稍后重试");
  }
}

function scrollToBottom() {
  const el = messagesEl.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

async function sendQuestion() {
  if (!question.value || loading.value) return;

  const q = question.value;
  question.value = "";
  loading.value = true;

  messages.value.push({ role: "user", type: "text", content: q });

  const stepIndex =
    messages.value.push({
      role: "assistant",
      type: "steps",
      steps: [],
    }) - 1;

  await nextTick();
  scrollToBottom();

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, session_id: getSessionId() }),
    });

    if (!response.body) throw new Error("服务器未返回流");

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();

      for (const evt of events) {
        const line = evt.trim();
        if (!line.startsWith("data:")) continue;

        let data;
        try {
          data = JSON.parse(line.replace(/^data:\s*/, ""));
        } catch {
          continue;
        }

        const steps = messages.value[stepIndex].steps;

        if (data.session_id) {
          // 会话标识事件:仅新建会话时服务端回传,保存供后续请求续接记忆
          saveSessionId(data.session_id);
        } else if (data.stage) {
          const last = steps.at(-1);
          if (last && last.status === "running") last.status = "success";
          // stage 可带 detail(如「改写问题」展示补全后的完整问题),提升多轮理解感知
          const text = data.detail ? `${data.stage}：${data.detail}` : data.stage;
          steps.push({ text, status: "running" });
        } else if (data.error) {
          const last = steps.at(-1);
          if (last) last.status = "error";
          latestReply.value = { type: "error", query: q, columns: [], rows: [] };
          messages.value.push({
            role: "assistant",
            type: "error",
            content: data.error,
            detail: data.detail || "",
          });
        } else if (data.answer) {
          const last = steps.at(-1);
          if (last) last.status = "success";
          latestReply.value = { type: "non_query", query: q, columns: [], rows: [] };
          messages.value.push({
            role: "assistant",
            type: "text",
            content: data.answer,
          });
        } else if (data.chart) {
          // 图表建议仅用于页面可视化，不改变 Excel 导出的表格数据源
          for (let i = messages.value.length - 1; i >= 0; i--) {
            const m = messages.value[i];
            if (m.type === "table") {
              m.chart = data.chart;
              break;
            }
          }
        } else if (Array.isArray(data.result)) {
          const last = steps.at(-1);
          if (last) last.status = "success";
          const columns = Object.keys(data.result[0] || {});
          latestReply.value = {
            type: "query",
            query: q,
            columns,
            rows: data.result.map((row) => ({ ...row })),
          };
          messages.value.push({
            role: "assistant",
            type: "table",
            columns,
            rows: data.result,
          });
        }

        await nextTick();
        scrollToBottom();
      }
    }
  } catch (e) {
    latestReply.value = { type: "error", query: q, columns: [], rows: [] };
    messages.value.push({
      role: "assistant",
      type: "error",
      content: "请求失败，请检查服务是否已启动",
      detail: e?.message || "",
    });
  } finally {
    loading.value = false;
    // 请求正常结束:最后一步若仍处于 running(如无 chart 事件时),统一标为成功
    const finalSteps = messages.value[stepIndex].steps;
    const finalLast = finalSteps.at(-1);
    if (finalLast && finalLast.status === "running") finalLast.status = "success";
    await nextTick();
    scrollToBottom();
  }
}
</script>

<style scoped>
/* 覆盖 Vite 默认居中 */
:global(html),
:global(body) {
  height: 100%;
  margin: 0;
}
:global(body) {
  display: block !important;
  place-items: unset !important;
}
:global(#app) {
  height: 100%;
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
}

/* 页面 */
.chat-page {
  height: 100%;
  overflow: hidden;
  background: #fff;
}

/* Excel 导出状态提示：信息明确、非阻塞，不遮挡查询结果 */
.export-toast {
  position: fixed;
  top: 22px;
  right: 24px;
  z-index: 20;
  max-width: min(420px, calc(100vw - 32px));
  padding: 12px 16px;
  border: 1px solid #dcdfe6;
  border-left: 4px solid #409eff;
  border-radius: 8px;
  background: #fff;
  color: #303133;
  box-shadow: 0 8px 24px rgba(31, 45, 61, 0.12);
  font-size: 14px;
  line-height: 1.5;
}
.export-toast-success {
  border-left-color: #2ecc71;
}
.export-toast-warning {
  border-left-color: #e6a23c;
}
.export-toast-error {
  border-left-color: #e74c3c;
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* 消息区 */
.messages {
  height: 100%;
  overflow-y: auto;
  padding: 20px 20% 160px;
}

.message-row {
  display: flex;
  margin-bottom: 14px;
}
.message-row.assistant {
  justify-content: flex-start;
}
.message-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 10px;
}

.bubble {
  max-width: min(820px, 72%);
  padding: 12px 14px;
  border-radius: 12px;
  background: #f5f5f5;
}
.message-row.user .bubble {
  background: #e6f4ff;
}

/* 数据卡片(表格/图表):与文本气泡区分——白底无灰底、更宽、内边距更大,
   让图表和表格成为页面视觉主体,而非与文字同规格的小气泡 */
.bubble-data {
  flex: 0 0 auto;
  width: min(960px, 94%);
  max-width: min(960px, 94%);
  padding: 16px 18px !important;
  background: #fff !important;
  border: 1px solid #ececec;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

/* 步骤 */
.steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.step {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.dot.running {
  background: #f1c40f;
}
.dot.success {
  background: #2ecc71;
}
.dot.error {
  background: #e74c3c;
}

/* 表格 */
.table-wrap {
  max-width: 100%;
  overflow-x: auto;
}

.result-table {
  width: max-content;
  min-width: 100%;
  table-layout: auto;
  border-collapse: collapse;
}

.result-table th,
.result-table td {
  border: 1px solid #ddd;
  padding: 6px 12px;
  white-space: nowrap;
  font-size: 13px;
  text-align: left;
}

.result-table th {
  background: #fafafa;
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 1;
}

/* 错误 */
.error-text {
  max-width: 100%;
}
.error-title {
  color: #e74c3c;
  font-weight: 600;
}
.error-detail {
  margin-top: 8px;
}
.error-detail-toggle {
  color: #909399;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}
.error-detail-body {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fdf0ef;
  border: 1px solid #f5c6c2;
  color: #b71c1c;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow: auto;
}

/* 悬浮输入框 */
.input-wrapper {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 24px;
  display: flex;
  justify-content: center;
  padding: 0 16px;
  pointer-events: none;
}

.input-box {
  pointer-events: auto;
  width: 100%;
  max-width: 900px;
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
}

.input-box input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
}

.input-box button {
  padding: 8px 18px;
  white-space: nowrap;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #409eff, #66b1ff);
  color: #fff;
  cursor: pointer;
}
.input-box button:disabled {
  opacity: 0.5;
}
.new-chat-btn {
  background: #fff !important;
  color: #606266 !important;
  border: 1px solid #dcdfe6 !important;
}
.export-btn {
  background: #fff !important;
  color: #409eff !important;
  border: 1px solid #409eff !important;
}
.export-btn:hover:not(:disabled) {
  background: #ecf5ff !important;
}
.new-chat-btn:hover {
  color: #409eff !important;
  border-color: #409eff !important;
}
.delete-chat-btn {
  background: #fff !important;
  color: #f56c6c !important;
  border: 1px solid #f56c6c !important;
}
.delete-chat-btn:hover {
  background: #fef0f0 !important;
}

.messages-bottom-spacer {
  height: 200px;
}

@media (max-width: 760px) {
  .messages {
    padding-left: 12px;
    padding-right: 12px;
  }
  .input-box {
    flex-wrap: wrap;
    border-radius: 20px;
  }
  .input-box input {
    flex: 1 0 calc(100% - 100px);
    min-width: 150px;
  }
  .input-box button {
    flex: 1 1 auto;
    padding-left: 12px;
    padding-right: 12px;
  }
  .export-toast {
    top: 16px;
    right: 16px;
  }
}
</style>
