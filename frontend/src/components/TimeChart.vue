<template>
  <canvas ref="canvas" height="160" />
</template>

<script>
import { Chart } from "chart.js/auto"
import { onBeforeUnmount, onMounted, ref, watch } from "vue"

export default {
  props: {
    chart: { type: Object, required: true },
  },
  setup(props) {
    const canvas = ref(null)
    let chart = null

    function color(name, fallback) {
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
      return value || fallback
    }

    function draw() {
      if (!canvas.value || !props.chart) return
      if (chart) chart.destroy()
      chart = new Chart(canvas.value, {
        type: "bar",
        data: {
          labels: props.chart.labels || [],
          datasets: [
            {
              label: props.chart.label || "Часы",
              data: props.chart.hours || [],
              backgroundColor: color("--accent", "#1f4e46"),
            },
          ],
        },
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: "bottom" } },
          scales: {
            x: { ticks: { maxRotation: 0, autoSkip: true } },
            y: { beginAtZero: true },
          },
        },
      })
    }

    onMounted(draw)
    watch(() => props.chart, draw)
    onBeforeUnmount(() => {
      if (chart) chart.destroy()
    })
    return { canvas }
  },
}
</script>
