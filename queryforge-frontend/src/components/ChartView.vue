<template>
  <div v-if="valid" ref="chartEl" class="chart-view"></div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";

const props = defineProps({
  chart: { type: Object, required: true },
  rows: { type: Array, required: true },
});

const chartEl = ref(null);
let instance = null;

// 字段存在性校验:LLM 建议的字段必须真实存在于结果列中,否则回退纯表格
const valid = computed(() => {
  const { chart, rows } = props;
  if (!chart || !rows || rows.length === 0) return false;
  if (!["bar", "line", "pie"].includes(chart.type)) return false;
  const cols = Object.keys(rows[0]);
  if (!cols.includes(chart.x)) return false;
  return (chart.y || []).every((y) => cols.includes(y));
});

function buildOption() {
  const { chart, rows } = props;
  const xData = rows.map((r) => String(r[chart.x]));
  const hasLegend = chart.y.length > 1;

  if (chart.type === "pie") {
    const yField = chart.y[0];
    return {
      title: chart.title
        ? { text: chart.title, left: "center", top: 8, textStyle: { fontSize: 14 } }
        : undefined,
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, orient: "horizontal" },
      series: [
        {
          type: "pie",
          radius: ["35%", "65%"],
          data: rows.map((r) => ({ name: String(r[chart.x]), value: Number(r[yField]) })),
          label: { formatter: "{b}\n{d}%" },
        },
      ],
    };
  }

  const series = (chart.y || []).map((y, i) => ({
    name: y,
    type: chart.type === "line" ? "line" : "bar",
    smooth: chart.type === "line",
    data: rows.map((r) => Number(r[y])),
    itemStyle: i === 1 ? { color: "#66b1ff" } : undefined,
  }));

  return {
    // 标题置顶居中,图例在其下方,grid 预留两者高度,避免标题与图例/图形重叠
    title: chart.title
      ? { text: chart.title, left: "center", top: 8, textStyle: { fontSize: 14 } }
      : undefined,
    tooltip: { trigger: "axis" },
    legend: hasLegend ? { top: 34 } : undefined,
    grid: { left: 56, right: 24, top: hasLegend ? 68 : 36, bottom: 40 },
    xAxis: { type: "category", data: xData, axisLabel: { rotate: xData.length > 8 ? 30 : 0 } },
    yAxis: { type: "value" },
    series,
  };
}

function render() {
  if (!valid.value || !chartEl.value) return;
  if (!instance) instance = echarts.init(chartEl.value);
  instance.setOption(buildOption(), true);
}

function resize() {
  instance && instance.resize();
}

onMounted(() => {
  render();
  window.addEventListener("resize", resize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  instance && instance.dispose();
  instance = null;
});

watch(() => [props.chart, props.rows], render, { deep: true });
</script>

<style scoped>
.chart-view {
  width: 100%;
  height: 360px;
  margin-bottom: 14px;
  border-radius: 8px;
  background: #fafbfc;
  border: 1px solid #f0f0f0;
}
</style>
