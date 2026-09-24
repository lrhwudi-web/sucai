export interface AuthUser {
  id: number;
  email: string;
  name: string;
  role: string;
  isAdmin: boolean;
  isSuperAdmin: boolean;
}

interface ApiUser {
  id: number;
  email: string;
  name: string;
  role: string;
  is_admin: boolean;
  is_super_admin: boolean;
}

export function apiEnabled(): boolean {
  return import.meta.env.VITE_USE_API !== "false";
}

function mapUser(user: ApiUser): AuthUser {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    isAdmin: user.is_admin,
    isSuperAdmin: user.is_super_admin,
  };
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  if (response.headers.get("content-type")?.includes("application/json")) {
    const payload = await response.json() as { detail?: string };
    return payload.detail || fallback;
  }
  return fallback;
}

export async function getSession(): Promise<AuthUser | null> {
  if (!apiEnabled()) return null;
  const response = await fetch("/api/session", {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(await errorMessage(response, "We could not verify your session."));
  const payload = await response.json() as { user: ApiUser };
  return mapUser(payload.user);
}

export async function loginCustomer(email: string, password: string): Promise<AuthUser> {
  if (!apiEnabled()) {
    await new Promise((resolve) => window.setTimeout(resolve, 650));
    const isAdmin = email.trim().toLowerCase().startsWith("admin");
    return { id: 0, email, name: isAdmin ? "Admin" : "Marketing", role: isAdmin ? "super_admin" : "overseas_customer", isAdmin, isSuperAdmin: isAdmin };
  }

  const form = new FormData();
  form.set("email", email);
  form.set("password", password);

  const response = await fetch("/login", {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response, "The email or password is incorrect. Please try again."));
  }
  const payload = await response.json() as { user: ApiUser };
  return mapUser(payload.user);
}

export async function logoutCustomer(): Promise<void> {
  if (!apiEnabled()) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return;
  }

  const response = await fetch("/logout", {
    method: "POST",
    headers: { Accept: "application/json" },
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error(await errorMessage(response, "We could not sign you out. Please try again."));
  }
}
