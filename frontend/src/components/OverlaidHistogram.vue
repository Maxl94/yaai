<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { HistogramData } from '@/types'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  dataA: HistogramData
  dataB: HistogramData
  fieldName: string
  labelA?: string
  labelB?: string
}>()

const option = computed(() => {
  const bucketsA = props.dataA.buckets
  const bucketsB = props.dataB.buckets
  
  // Use A's buckets as labels (they should be aligned)
  const labels = bucketsA.map((b) => `${b.range_start.toFixed(1)}`)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    legend: {
      data: [props.labelA || 'Period A', props.labelB || 'Period B'],
      top: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '15%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: {
        rotate: 45,
        fontSize: 10,
      },
    },
    yAxis: {
      type: 'value',
      name: 'Count',
    },
    series: [
      {
        name: props.labelA || 'Period A',
        type: 'bar',
        data: bucketsA.map((b) => b.count),
        itemStyle: {
          color: 'rgba(13, 148, 136, 0.7)',
        },
        barWidth: '35%',
      },
      {
        name: props.labelB || 'Period B',
        type: 'bar',
        data: bucketsB.map((b) => b.count),
        itemStyle: {
          color: 'rgba(245, 158, 11, 0.45)',
        },
        barWidth: '35%',
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 220px" />
</template>
