/**
 * TypeScript types matching backend models
 */

export type TaskStatus = 'wtg' | 'rdy' | 'ip' | 'rev' | 'app' | 'hld' | 'fin' | 'omt';
export type Priority = 'low' | 'medium' | 'high' | 'critical';
export type Department = 'modeling' | 'rigging' | 'surfacing' | 'animation' | 'fx' | 'lighting' | 'rendering' | 'compositing' | 'editorial' | 'concept' | 'production';
export type AssetType = 'character' | 'prop' | 'environment' | 'fx' | 'vehicle' | 'matte_painting';
export type CommentType = 'note' | 'approval' | 'revision';

export interface User {
  id: number;
  email: string;
  name: string;
  avatar_url?: string | null;
  department?: Department | null;
  role?: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Project {
  id: number;
  name: string;
  code: string;
  description?: string | null;
  thumbnail_url?: string | null;
  status: TaskStatus;
  start_date?: string | null;
  end_date?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Sequence {
  id: number;
  project_id: number;
  name: string;
  code: string;
  description?: string | null;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
}

export interface Shot {
  id: number;
  sequence_id: number;
  name: string;
  code: string;
  description?: string | null;
  thumbnail_url?: string | null;
  status: TaskStatus;
  priority: Priority;
  frame_start?: number | null;
  frame_end?: number | null;
  frame_duration?: number | null;
  fps: number;
  custom_metadata?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: number;
  project_id: number;
  name: string;
  code: string;
  asset_type: AssetType;
  description?: string | null;
  thumbnail_url?: string | null;
  status: TaskStatus;
  priority: Priority;
  custom_metadata?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: number;
  name: string;
  description?: string | null;
  department: Department;
  status: TaskStatus;
  priority: Priority;
  assignee_id?: number | null;
  shot_id?: number | null;
  asset_id?: number | null;
  start_date?: string | null;
  due_date?: string | null;
  completed_date?: string | null;
  estimated_hours?: number | null;
  actual_hours?: number | null;
  created_at: string;
  updated_at: string;
}

export interface Version {
  id: number;
  name: string;
  version_number: number;
  description?: string | null;
  file_path: string;
  file_name: string;
  file_size?: number | null;
  mime_type?: string | null;
  thumbnail_url?: string | null;
  duration?: number | null;
  fps?: number | null;
  resolution_width?: number | null;
  resolution_height?: number | null;
  codec?: string | null;
  shot_id?: number | null;
  asset_id?: number | null;
  uploaded_by_id: number;
  uploaded_at: string;
  review_status: TaskStatus;
}

export interface Comment {
  id: number;
  version_id: number;
  author_id: number;
  text: string;
  comment_type: CommentType;
  frame_number?: number | null;
  timecode?: string | null;
  annotation_data?: AnnotationData | null;
  parent_comment_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface CommentWithAuthor extends Comment {
  author: User;
  replies?: CommentWithAuthor[];
}

export interface AnnotationData {
  shapes: AnnotationShape[];
}

export interface AnnotationShape {
  type: 'circle' | 'arrow' | 'box' | 'text' | 'freehand';
  color: string;
  // Circle
  x?: number;
  y?: number;
  radius?: number;
  // Arrow
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  // Box
  width?: number;
  height?: number;
  // Text
  text?: string;
  fontSize?: number;
  // Freehand
  points?: {x: number; y: number}[];
}

export interface Activity {
  id: number;
  user_id?: number | null;
  action: string;
  entity_type: string;
  entity_id: number;
  details?: Record<string, any> | null;
  created_at: string;
}

// Create types
export interface CreateProject {
  name: string;
  code: string;
  description?: string;
  status?: TaskStatus;
}

export interface CreateShot {
  sequence_id: number;
  name: string;
  code: string;
  description?: string;
  status?: TaskStatus;
  priority?: Priority;
  frame_start?: number;
  frame_end?: number;
  fps?: number;
}

export interface CreateVersion {
  name: string;
  version_number: number;
  description?: string;
  file_path: string;
  file_name: string;
  file_size?: number;
  mime_type?: string;
  duration?: number;
  fps?: number;
  resolution_width?: number;
  resolution_height?: number;
  shot_id?: number;
  asset_id?: number;
  uploaded_by_id: number;
}

export interface CreateComment {
  version_id: number;
  author_id: number;
  text: string;
  comment_type?: CommentType;
  frame_number?: number;
  timecode?: string;
  annotation_data?: AnnotationData;
  parent_comment_id?: number;
}

// Status helpers
export const STATUS_LABELS: Record<TaskStatus, string> = {
  wtg: 'Waiting',
  rdy: 'Ready',
  ip: 'In Progress',
  rev: 'Review',
  app: 'Approved',
  hld: 'On Hold',
  fin: 'Final',
  omt: 'Omitted'
};

export const STATUS_COLORS: Record<TaskStatus, string> = {
  wtg: '#6B7280',  // gray
  rdy: '#3B82F6',  // blue
  ip: '#8B5CF6',   // purple
  rev: '#F59E0B',  // orange
  app: '#10B981',  // green
  hld: '#EF4444',  // red
  fin: '#059669',  // emerald
  omt: '#374151'   // dark gray
};

export const PRIORITY_COLORS: Record<Priority, string> = {
  low: '#10B981',
  medium: '#F59E0B',
  high: '#EF4444',
  critical: '#DC2626'
};
