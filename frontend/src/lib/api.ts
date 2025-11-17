/**
 * API client for backend communication
 */

import axios from 'axios';
import type {
  User, Project, Sequence, Shot, Asset, Task, Version, Comment, Activity,
  CreateProject, CreateShot, CreateVersion, CreateComment, CommentWithAuthor
} from './types';

const API_BASE_URL = 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Projects
export const projectsApi = {
  list: () => api.get<Project[]>('/projects/'),
  get: (id: number) => api.get<Project>(`/projects/${id}`),
  create: (data: CreateProject) => api.post<Project>('/projects/', data),
  update: (id: number, data: Partial<Project>) => api.put<Project>(`/projects/${id}`, data),
  delete: (id: number) => api.delete(`/projects/${id}`),
};

// Sequences
export const sequencesApi = {
  list: (projectId: number) => api.get<Sequence[]>('/sequences/', { params: { project_id: projectId } }),
  get: (id: number) => api.get<Sequence>(`/sequences/${id}`),
  create: (data: { project_id: number; name: string; code: string; description?: string }) =>
    api.post<Sequence>('/sequences/', data),
  update: (id: number, data: Partial<Sequence>) => api.put<Sequence>(`/sequences/${id}`, data),
  delete: (id: number) => api.delete(`/sequences/${id}`),
};

// Shots
export const shotsApi = {
  listBySequence: (sequenceId: number) => api.get<Shot[]>('/shots/', { params: { sequence_id: sequenceId } }),
  listByProject: (projectId: number) => api.get<Shot[]>('/shots/', { params: { project_id: projectId } }),
  get: (id: number) => api.get<Shot>(`/shots/${id}`),
  create: (data: CreateShot) => api.post<Shot>('/shots/', data),
  update: (id: number, data: Partial<Shot>) => api.put<Shot>(`/shots/${id}`, data),
  delete: (id: number) => api.delete(`/shots/${id}`),
};

// Assets
export const assetsApi = {
  list: (projectId: number) => api.get<Asset[]>('/assets/', { params: { project_id: projectId } }),
  get: (id: number) => api.get<Asset>(`/assets/${id}`),
  create: (data: Partial<Asset> & { project_id: number; name: string; code: string; asset_type: string }) =>
    api.post<Asset>('/assets/', data),
  update: (id: number, data: Partial<Asset>) => api.put<Asset>(`/assets/${id}`, data),
  delete: (id: number) => api.delete(`/assets/${id}`),
};

// Tasks
export const tasksApi = {
  listByShot: (shotId: number) => api.get<Task[]>('/tasks/', { params: { shot_id: shotId } }),
  listByAsset: (assetId: number) => api.get<Task[]>('/tasks/', { params: { asset_id: assetId } }),
  listByAssignee: (userId: number) => api.get<Task[]>('/tasks/', { params: { assignee_id: userId } }),
  get: (id: number) => api.get<Task>(`/tasks/${id}`),
  create: (data: Partial<Task> & { name: string; department: string }) =>
    api.post<Task>('/tasks/', data),
  update: (id: number, data: Partial<Task>) => api.put<Task>(`/tasks/${id}`, data),
  delete: (id: number) => api.delete(`/tasks/${id}`),
};

// Versions
export const versionsApi = {
  listByShot: (shotId: number) => api.get<Version[]>('/versions/', { params: { shot_id: shotId } }),
  listByAsset: (assetId: number) => api.get<Version[]>('/versions/', { params: { asset_id: assetId } }),
  get: (id: number) => api.get<Version>(`/versions/${id}`),
  create: (data: CreateVersion) => api.post<Version>('/versions/', data),
  update: (id: number, data: Partial<Version>) => api.put<Version>(`/versions/${id}`, data),
  delete: (id: number) => api.delete(`/versions/${id}`),
  validatePath: (filePath: string) =>
    api.post('/versions/validate-path', null, { params: { file_path: filePath } }),
};

// Comments
export const commentsApi = {
  list: (versionId: number) => api.get<Comment[]>('/comments/', { params: { version_id: versionId } }),
  get: (id: number) => api.get<CommentWithAuthor>(`/comments/${id}`),
  create: (data: CreateComment) => api.post<Comment>('/comments/', data),
  update: (id: number, data: Partial<Comment>) => api.put<Comment>(`/comments/${id}`, data),
  delete: (id: number) => api.delete(`/comments/${id}`),
  getReplies: (id: number) => api.get<Comment[]>(`/comments/${id}/replies`),
};

// Users
export const usersApi = {
  list: () => api.get<User[]>('/users/'),
  get: (id: number) => api.get<User>(`/users/${id}`),
  create: (data: { email: string; name: string; password: string; department?: string; role?: string }) =>
    api.post<User>('/users/', data),
  update: (id: number, data: Partial<User>) => api.put<User>(`/users/${id}`, data),
};

// Activity
export const activityApi = {
  list: (limit = 50) => api.get<Activity[]>('/activity/', { params: { limit } }),
  listByEntity: (entityType: string, entityId: number) =>
    api.get<Activity[]>('/activity/', { params: { entity_type: entityType, entity_id: entityId } }),
  create: (data: { action: string; entity_type: string; entity_id: number; user_id?: number; details?: any }) =>
    api.post<Activity>('/activity/', data),
};

export default api;
