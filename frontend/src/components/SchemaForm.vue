<script setup lang="ts">
import { enumOf, fieldKind, type Button, type FormValues } from '../server'

// The form of a button: a field per property of the verb's JSON Schema --
// a choice, a flag, a text, lines of a list, or JSON text for what the page
// cannot draw. A required field is marked so.
const props = defineProps<{ button: Button }>()
const values = defineModel<FormValues>('values', { required: true })
const required = (name: string) => (props.button.schema.required ?? []).includes(name)
</script>

<template>
  <div class="form" data-test="form">
    <label
      v-for="(field, name) in button.schema.properties"
      :key="name"
      :data-test="`field-${name}`"
    >
      {{ field.title ?? name }}<span v-if="required(String(name))" data-test="required">*</span>
      <select
        v-if="fieldKind(field) === 'enum'"
        v-model="values.text[name]"
        :required="required(String(name))"
      >
        <option v-for="choice in enumOf(field)" :key="choice" :value="choice">{{ choice }}</option>
      </select>
      <input
        v-else-if="fieldKind(field) === 'boolean'"
        v-model="values.flag[name]"
        type="checkbox"
      />
      <textarea v-else-if="fieldKind(field) === 'list'" v-model="values.text[name]" />
      <textarea
        v-else-if="fieldKind(field) === 'json'"
        v-model="values.text[name]"
        data-test="json"
      />
      <input v-else v-model="values.text[name]" :required="required(String(name))" />
    </label>
  </div>
</template>
