import { create } from 'zustand';
import { devtools, persist, subscribeWithSelector } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';

// ============ USER STORE ============

interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
  role: 'user' | 'admin' | 'developer';
  preferences: {
    theme: 'light' | 'dark' | 'system';
    notifications: boolean;
    language: string;
  };
}

interface UserState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  
  // Actions
  setUser: (user: User) => void;
  updateUser: (updates: Partial<User>) => void;
  updatePreferences: (preferences: Partial<User['preferences']>) => void;
  logout: () => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useUserStore = create<UserState>()(
  devtools(
    persist(
      subscribeWithSelector(
        immer((set) => ({
          user: null,
          isAuthenticated: false,
          isLoading: false,
          error: null,

          setUser: (user) =>
            set((state) => {
              state.user = user;
              state.isAuthenticated = true;
              state.error = null;
            }),

          updateUser: (updates) =>
            set((state) => {
              if (state.user) {
                Object.assign(state.user, updates);
              }
            }),

          updatePreferences: (preferences) =>
            set((state) => {
              if (state.user) {
                Object.assign(state.user.preferences, preferences);
              }
            }),

          logout: () =>
            set((state) => {
              state.user = null;
              state.isAuthenticated = false;
            }),

          setLoading: (loading) =>
            set((state) => {
              state.isLoading = loading;
            }),

          setError: (error) =>
            set((state) => {
              state.error = error;
            }),
        }))
      ),
      {
        name: 'user-storage',
        partialize: (state) => ({ user: state.user }),
      }
    ),
    { name: 'UserStore' }
  )
);

// ============ PROJECT STORE ============

interface Project {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'paused' | 'completed' | 'archived';
  stack: string[];
  agents: string[];
  createdAt: Date;
  updatedAt: Date;
}

interface Task {
  id: string;
  projectId: string;
  title: string;
  description: string;
  status: 'pending' | 'in-progress' | 'completed' | 'failed';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  assignedAgent: string | null;
  createdAt: Date;
  completedAt: Date | null;
}

interface ProjectState {
  projects: Project[];
  currentProject: Project | null;
  tasks: Task[];
  isLoading: boolean;
  
  // Actions
  setProjects: (projects: Project[]) => void;
  addProject: (project: Project) => void;
  updateProject: (id: string, updates: Partial<Project>) => void;
  deleteProject: (id: string) => void;
  setCurrentProject: (project: Project | null) => void;
  
  setTasks: (tasks: Task[]) => void;
  addTask: (task: Task) => void;
  updateTask: (id: string, updates: Partial<Task>) => void;
  deleteTask: (id: string) => void;
  
  setLoading: (loading: boolean) => void;
}

export const useProjectStore = create<ProjectState>()(
  devtools(
    subscribeWithSelector(
      immer((set) => ({
        projects: [],
        currentProject: null,
        tasks: [],
        isLoading: false,

        setProjects: (projects) =>
          set((state) => {
            state.projects = projects;
          }),

        addProject: (project) =>
          set((state) => {
            state.projects.push(project);
          }),

        updateProject: (id, updates) =>
          set((state) => {
            const index = state.projects.findIndex((p) => p.id === id);
            if (index !== -1) {
              Object.assign(state.projects[index], updates);
            }
            if (state.currentProject?.id === id) {
              Object.assign(state.currentProject, updates);
            }
          }),

        deleteProject: (id) =>
          set((state) => {
            state.projects = state.projects.filter((p) => p.id !== id);
            if (state.currentProject?.id === id) {
              state.currentProject = null;
            }
          }),

        setCurrentProject: (project) =>
          set((state) => {
            state.currentProject = project;
          }),

        setTasks: (tasks) =>
          set((state) => {
            state.tasks = tasks;
          }),

        addTask: (task) =>
          set((state) => {
            state.tasks.push(task);
          }),

        updateTask: (id, updates) =>
          set((state) => {
            const index = state.tasks.findIndex((t) => t.id === id);
            if (index !== -1) {
              Object.assign(state.tasks[index], updates);
            }
          }),

        deleteTask: (id) =>
          set((state) => {
            state.tasks = state.tasks.filter((t) => t.id !== id);
          }),

        setLoading: (loading) =>
          set((state) => {
            state.isLoading = loading;
          }),
      }))
    ),
    { name: 'ProjectStore' }
  )
);

// ============ AGENT STORE ============

interface Agent {
  id: string;
  name: string;
  type: 'lead' | 'frontend' | 'backend' | 'aiml' | 'design' | 'devops' | 'qa';
  status: 'idle' | 'working' | 'paused' | 'error';
  currentTask: string | null;
  metrics: {
    tasksCompleted: number;
    tokensUsed: number;
    successRate: number;
    avgDuration: number;
  };
}

interface AgentState {
  agents: Agent[];
  selectedAgent: Agent | null;
  
  // Actions
  setAgents: (agents: Agent[]) => void;
  updateAgent: (id: string, updates: Partial<Agent>) => void;
  setSelectedAgent: (agent: Agent | null) => void;
  updateAgentStatus: (id: string, status: Agent['status']) => void;
}

export const useAgentStore = create<AgentState>()(
  devtools(
    subscribeWithSelector(
      immer((set) => ({
        agents: [],
        selectedAgent: null,

        setAgents: (agents) =>
          set((state) => {
            state.agents = agents;
          }),

        updateAgent: (id, updates) =>
          set((state) => {
            const index = state.agents.findIndex((a) => a.id === id);
            if (index !== -1) {
              Object.assign(state.agents[index], updates);
            }
            if (state.selectedAgent?.id === id) {
              Object.assign(state.selectedAgent, updates);
            }
          }),

        setSelectedAgent: (agent) =>
          set((state) => {
            state.selectedAgent = agent;
          }),

        updateAgentStatus: (id, status) =>
          set((state) => {
            const index = state.agents.findIndex((a) => a.id === id);
            if (index !== -1) {
              state.agents[index].status = status;
            }
          }),
      }))
    ),
    { name: 'AgentStore' }
  )
);

// ============ UI STORE ============

interface UIState {
  sidebarOpen: boolean;
  commandPaletteOpen: boolean;
  modalStack: string[];
  toasts: Array<{
    id: string;
    type: 'success' | 'error' | 'warning' | 'info';
    message: string;
    duration?: number;
  }>;
  
  // Actions
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleCommandPalette: () => void;
  openModal: (id: string) => void;
  closeModal: (id: string) => void;
  closeAllModals: () => void;
  addToast: (toast: Omit<UIState['toasts'][0], 'id'>) => void;
  removeToast: (id: string) => void;
}

export const useUIStore = create<UIState>()(
  devtools(
    immer((set) => ({
      sidebarOpen: true,
      commandPaletteOpen: false,
      modalStack: [],
      toasts: [],

      toggleSidebar: () =>
        set((state) => {
          state.sidebarOpen = !state.sidebarOpen;
        }),

      setSidebarOpen: (open) =>
        set((state) => {
          state.sidebarOpen = open;
        }),

      toggleCommandPalette: () =>
        set((state) => {
          state.commandPaletteOpen = !state.commandPaletteOpen;
        }),

      openModal: (id) =>
        set((state) => {
          if (!state.modalStack.includes(id)) {
            state.modalStack.push(id);
          }
        }),

      closeModal: (id) =>
        set((state) => {
          state.modalStack = state.modalStack.filter((m) => m !== id);
        }),

      closeAllModals: () =>
        set((state) => {
          state.modalStack = [];
        }),

      addToast: (toast) =>
        set((state) => {
          const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
          state.toasts.push({ ...toast, id });
        }),

      removeToast: (id) =>
        set((state) => {
          state.toasts = state.toasts.filter((t) => t.id !== id);
        }),
    })),
    { name: 'UIStore' }
  )
);

// ============ SELECTORS ============

// User selectors
export const selectUser = (state: UserState) => state.user;
export const selectIsAuthenticated = (state: UserState) => state.isAuthenticated;
export const selectUserPreferences = (state: UserState) => state.user?.preferences;

// Project selectors
export const selectProjects = (state: ProjectState) => state.projects;
export const selectCurrentProject = (state: ProjectState) => state.currentProject;
export const selectTasks = (state: ProjectState) => state.tasks;
export const selectTasksByStatus = (status: Task['status']) => (state: ProjectState) =>
  state.tasks.filter((t) => t.status === status);
export const selectTasksByProject = (projectId: string) => (state: ProjectState) =>
  state.tasks.filter((t) => t.projectId === projectId);

// Agent selectors
export const selectAgents = (state: AgentState) => state.agents;
export const selectAgentById = (id: string) => (state: AgentState) =>
  state.agents.find((a) => a.id === id);
export const selectActiveAgents = (state: AgentState) =>
  state.agents.filter((a) => a.status === 'working');

// UI selectors
export const selectSidebarOpen = (state: UIState) => state.sidebarOpen;
export const selectCommandPaletteOpen = (state: UIState) => state.commandPaletteOpen;
export const selectToasts = (state: UIState) => state.toasts;
