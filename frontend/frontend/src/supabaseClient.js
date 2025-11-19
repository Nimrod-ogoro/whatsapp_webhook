import { createClient } from '@supabase/supabase-js';

// Read environment variables
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_KEY;

// Safety check: ensure both env vars exist
if (!supabaseUrl) {
  throw new Error("VITE_SUPABASE_URL is missing in your .env file");
}
if (!supabaseKey) {
  throw new Error("VITE_SUPABASE_KEY is missing in your .env file");
}

// Initialize Supabase client
export const supabase = createClient(supabaseUrl, supabaseKey);


