import js from '@eslint/js'
import ts from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default ts.config(
  {
    ignores: ['dist/**', 'coverage/**', 'node_modules/**'],
  },

  js.configs.recommended,

  ...ts.configs.strict,

  ...pluginVue.configs['flat/recommended'],

  // Vue files: use typescript-eslint parser for <script> blocks
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: ts.parser,
      },
    },
  },

  // Project-specific overrides
  {
    rules: {
      // TypeScript already handles undefined variables — disable ESLint's check
      // https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
      'no-undef': 'off',

      // Disable formatting rules (use a dedicated formatter instead)
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/html-closing-bracket-spacing': 'off',
      'vue/attributes-order': 'off',

      'vue/multi-word-component-names': 'off',
      'vue/valid-v-slot': ['error', { allowModifiers: true }],

      // Allow non-null assertions (common pattern with Vue refs)
      '@typescript-eslint/no-non-null-assertion': 'off',

      // Allow unused vars prefixed with underscore
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
)
