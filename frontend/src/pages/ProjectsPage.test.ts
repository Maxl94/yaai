import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ProjectsPage from '@/pages/ProjectsPage.vue'
import { useAuthStore } from '@/stores/auth'
import { projectsApi } from '@/api/projects'
import { authApi } from '@/api/auth'
import { createTestVuetify, makeProject, makeUser } from '@/test/helpers'
import type { ProjectMember } from '@/types'

vi.mock('@/api/projects', () => ({
  projectsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    listMembers: vi.fn(),
    addMember: vi.fn(),
    updateMemberRole: vi.fn(),
    removeMember: vi.fn(),
  },
}))
vi.mock('@/api/auth', () => ({ authApi: { listUsers: vi.fn(), listServiceAccounts: vi.fn() } }))

const projects = [
  makeProject({ id: 'default', name: 'default', is_default: true, model_count: 2, my_role: 'owner' }),
  makeProject({ id: 'empty', name: 'empty-proj', model_count: 0, my_role: 'owner' }),
  makeProject({ id: 'full', name: 'full-proj', model_count: 3, my_role: 'viewer' }),
]

const member: ProjectMember = {
  id: 'mem1',
  project_id: 'empty',
  principal_type: 'user',
  user_id: 'u-bob',
  service_account_id: null,
  name: 'bob',
  email: 'bob@example.com',
  role: 'editor',
  created_at: '2026-01-01T00:00:00Z',
}

let wrapper: VueWrapper | null = null

async function mountPage(role: 'owner' | 'viewer', projectList = projects) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.authConfig = { enabled: true, local_enabled: true, google_oauth_enabled: false, allow_registration: false }
  auth.user = makeUser({ role })
  vi.mocked(projectsApi.list).mockResolvedValue(projectList)
  wrapper = mount(ProjectsPage, { global: { plugins: [pinia, createTestVuetify()] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

const button = (label: string) => wrapper!.find(`button[aria-label="${label}"]`)
const bodyButton = (text: string) =>
  [...document.body.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)

beforeEach(() => {
  localStorage.clear()
  vi.mocked(projectsApi.listMembers).mockReset().mockResolvedValue([member])
  vi.mocked(projectsApi.addMember).mockReset().mockResolvedValue(member)
  vi.mocked(projectsApi.create).mockReset().mockResolvedValue(projects[1]!)
  vi.mocked(projectsApi.delete).mockReset().mockResolvedValue()
  vi.mocked(authApi.listUsers).mockReset().mockResolvedValue([makeUser({ id: 'u-carol', username: 'carol' })])
  vi.mocked(authApi.listServiceAccounts).mockReset().mockResolvedValue([])
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('ProjectsPage visibility', () => {
  it('lets a global owner create, edit, manage and delete projects', async () => {
    await mountPage('owner')
    expect(wrapper!.find('[data-testid="create-project"]').exists()).toBe(true)
    expect(button('Members of empty-proj').exists()).toBe(true)
    expect(button('Edit full-proj').exists()).toBe(true)
    expect(button('Delete empty-proj').attributes('disabled')).toBeUndefined()
  })

  it('disables deletion of the default project and of non-empty projects', async () => {
    await mountPage('owner')
    expect(button('Delete default').attributes('disabled')).toBeDefined()
    expect(button('Delete full-proj').attributes('disabled')).toBeDefined()
  })

  it('gives a project owner member management but no create or delete', async () => {
    await mountPage('viewer')
    expect(wrapper!.find('[data-testid="create-project"]').exists()).toBe(false)
    expect(button('Members of empty-proj').exists()).toBe(true)
    expect(button('Edit empty-proj').exists()).toBe(true)
    expect(button('Delete empty-proj').exists()).toBe(false)
    expect(button('Members of full-proj').exists()).toBe(false)
  })

  it('shows projects read-only to a plain viewer', async () => {
    await mountPage('viewer', [makeProject({ id: 'full', name: 'full-proj', my_role: 'viewer' })])
    expect(wrapper!.text()).toContain('full-proj')
    expect(wrapper!.find('[data-testid="create-project"]').exists()).toBe(false)
    expect(wrapper!.findAll('button[aria-label^="Members of"], button[aria-label^="Edit "], button[aria-label^="Delete "]'),
    ).toHaveLength(0)
  })

  it('marks the default project with a badge', async () => {
    await mountPage('owner')
    expect(wrapper!.text()).toContain('default')
    expect(wrapper!.text()).toContain('3')
  })
})

describe('ProjectsPage project management', () => {
  it('creates a project with a trimmed name', async () => {
    await mountPage('owner')
    await wrapper!.find('[data-testid="create-project"]').trigger('click')
    await flushPromises()
    const nameInput = document.body.querySelector<HTMLInputElement>('.v-dialog input')!
    nameInput.value = '  team-x  '
    nameInput.dispatchEvent(new Event('input'))
    await flushPromises()
    bodyButton('Create')!.click()
    await flushPromises()
    expect(projectsApi.create).toHaveBeenCalledWith({ name: 'team-x', description: undefined })
  })

  it('shows the API error when deletion is rejected', async () => {
    vi.mocked(projectsApi.delete).mockRejectedValue({ status: 409, message: 'x', detail: 'Project still contains 1 model(s)' })
    await mountPage('owner')
    await button('Delete empty-proj').trigger('click')
    await flushPromises()
    bodyButton('Delete')!.click()
    await flushPromises()
    expect(document.body.textContent).toContain('Project still contains 1 model(s)')
  })
})

describe('ProjectsPage members', () => {
  async function openMembers(role: 'owner' | 'viewer') {
    await mountPage(role)
    await button('Members of empty-proj').trigger('click')
    await flushPromises()
  }

  it('lists members of the project', async () => {
    await openMembers('viewer')
    expect(projectsApi.listMembers).toHaveBeenCalledWith('empty')
    expect(document.body.textContent).toContain('bob@example.com')
  })

  it('lets a project owner add a user by username without listing users', async () => {
    await openMembers('viewer')
    expect(authApi.listUsers).not.toHaveBeenCalled()
    const usernameInput = [...document.body.querySelectorAll<HTMLInputElement>('input')].find(
      (i) => i.closest('.v-field')?.textContent?.includes('Username'),
    )!
    usernameInput.value = 'dave'
    usernameInput.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(document.body.querySelector('[data-testid="add-member"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(projectsApi.addMember).toHaveBeenCalledWith('empty', { username: 'dave', role: 'viewer' })
  })

  it('lets a global owner pick a user from the user list', async () => {
    await openMembers('owner')
    expect(authApi.listUsers).toHaveBeenCalled()
    const autocomplete = wrapper!.findAllComponents({ name: 'VAutocomplete' })[0]
    expect(autocomplete).toBeDefined()
    autocomplete!.vm.$emit('update:modelValue', 'u-carol')
    await flushPromises()
    ;(document.body.querySelector('[data-testid="add-member"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(projectsApi.addMember).toHaveBeenCalledWith('empty', { user_id: 'u-carol', role: 'viewer' })
  })

  it('shows API errors such as a duplicate member', async () => {
    vi.mocked(projectsApi.addMember).mockRejectedValue({ status: 409, message: 'x', detail: 'Already a member' })
    await openMembers('viewer')
    const usernameInput = [...document.body.querySelectorAll<HTMLInputElement>('input')].find(
      (i) => i.closest('.v-field')?.textContent?.includes('Username'),
    )!
    usernameInput.value = 'bob'
    usernameInput.dispatchEvent(new Event('input'))
    await flushPromises()
    ;(document.body.querySelector('[data-testid="add-member"]') as HTMLButtonElement).click()
    await flushPromises()
    expect(document.body.querySelector('[data-testid="members-error"]')?.textContent).toContain('Already a member')
  })

  it('removes a member after confirmation and reports last-owner conflicts', async () => {
    vi.mocked(projectsApi.removeMember).mockRejectedValue({ status: 409, message: 'x', detail: 'Cannot remove the last owner' })
    await openMembers('viewer')
    ;(document.body.querySelector('button[aria-label="Remove bob"]') as HTMLButtonElement).click()
    await flushPromises()
    bodyButton('Remove')!.click()
    await flushPromises()
    expect(projectsApi.removeMember).toHaveBeenCalledWith('empty', 'mem1')
    expect(document.body.querySelector('[data-testid="members-error"]')?.textContent).toContain('last owner')
  })
})

describe('ProjectsPage membership edge cases', () => {
  const reducedProjects = [
    projects[0]!,
    makeProject({ id: 'empty', name: 'empty-proj', my_role: 'editor' }),
  ]

  async function openMembers() {
    await mountPage('viewer')
    await button('Members of empty-proj').trigger('click')
    await flushPromises()
  }

  it('closes the members dialog when an owner demotes themselves', async () => {
    await openMembers()
    vi.mocked(projectsApi.updateMemberRole).mockResolvedValue({ ...member, role: 'editor' })
    vi.mocked(projectsApi.list).mockResolvedValue(reducedProjects)
    vi.mocked(projectsApi.listMembers).mockClear()

    const roleSelect = wrapper!.findAllComponents({ name: 'VSelect' }).find((c) => c.props('modelValue') === 'editor')!
    roleSelect.vm.$emit('update:modelValue', 'viewer')
    await flushPromises()

    expect(projectsApi.updateMemberRole).toHaveBeenCalledWith('empty', 'mem1', 'viewer')
    expect(projectsApi.listMembers).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('You no longer manage this project')
    expect(button('Members of empty-proj').exists()).toBe(false)
  })

  it('closes the members dialog when an owner removes themselves', async () => {
    await openMembers()
    vi.mocked(projectsApi.removeMember).mockResolvedValue()
    vi.mocked(projectsApi.list).mockResolvedValue([projects[0]!])
    vi.mocked(projectsApi.listMembers).mockClear()
    ;(document.body.querySelector('button[aria-label="Remove bob"]') as HTMLButtonElement).click()
    await flushPromises()
    bodyButton('Remove')!.click()
    await flushPromises()

    expect(projectsApi.listMembers).not.toHaveBeenCalled()
    expect(wrapper!.text()).toContain('You no longer manage this project')
  })

  it('keeps the dialog open and shows the conflict when a change is rejected', async () => {
    await openMembers()
    vi.mocked(projectsApi.updateMemberRole).mockRejectedValue({ status: 409, message: 'x', detail: 'Cannot demote the last owner' })
    const roleSelect = wrapper!.findAllComponents({ name: 'VSelect' }).find((c) => c.props('modelValue') === 'editor')!
    roleSelect.vm.$emit('update:modelValue', 'viewer')
    await flushPromises()

    expect(document.body.querySelector('[data-testid="members-error"]')?.textContent).toContain('last owner')
    expect(wrapper!.text()).not.toContain('You no longer manage this project')
  })

  it('reports a failed reload even after an earlier successful load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    await mountPage('owner')
    vi.mocked(projectsApi.delete).mockResolvedValue()
    vi.mocked(projectsApi.list).mockRejectedValue({ status: 500, message: 'x', detail: 'Database unavailable' })
    await button('Delete empty-proj').trigger('click')
    await flushPromises()
    bodyButton('Delete')!.click()
    await flushPromises()

    expect(wrapper!.text()).toContain('Database unavailable')
  })

  it('explains to users without projects how to get access', async () => {
    await mountPage('viewer', [])
    expect(wrapper!.find('[data-testid="no-projects"]').text()).toContain('not a member of any project yet')
  })
})
