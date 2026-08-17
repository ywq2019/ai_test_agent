<template>
  <el-dropdown v-if="fnList && fnList.length" trigger="click" @command="onCommand">
    <el-button
      size="small"
      text
      style="font-family:monospace;color:#909399;padding:0 4px;min-width:36px"
    >ƒ(x)</el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item v-for="fn in fnList" :key="fn.value" :command="fn.value">
          <span style="font-family:monospace;font-size:12px">{{ fn.value }}</span>
          <span style="color:#aaa;font-size:11px;margin-left:8px">{{ fn.desc }}</span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
defineProps({
  fnList: { type: Array, default: () => [] },
})

const emit = defineEmits(['insert'])
const onCommand = (fn) => emit('insert', fn)
</script>
