<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { CategoricalData } from '@/types'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  dataA: CategoricalData
  dataB: CategoricalData
  fieldName: string
  labelA?: string
  labelB?: string
}>()

const option = computed(() => {
  // Combine categories from both datasets
  const allCategories = new Set([
    ...props.dataA.categories.map((c) => c.value),
    ...props.dataB.categories.map((c) => c.value),
  ])
  const categories = Array.from(allCategories).slice(0, 10)

  const getCount = (data: CategoricalData, cat: string) => {
    return data.categories.find((c) => c.value === cat)?.count || 0
  }

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
      data: categories,
      axisLabel: {
        rotate: 45,
        fontSize: 10,
        interval: 0,
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
        data: categories.map((c) => getCount(props.dataA, c)),
        itemStyle: {
          color: 'rgba(13, 148, 136, 0.7)',
        },
      },
      {
        name: props.labelB || 'Period B',
        type: 'bar',
        data: categories.map((c) => getCount(props.dataB, c)),
        itemStyle: {
          color: 'rgba(245, 158, 11, 0.45)',
        },
      },
    ],
  }
})
</script>

<template>
  <v-chart :option="option" autoresize style="height: 220px" />
</template>
