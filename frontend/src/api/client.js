/**
 * Lightweight Frontend API Helper for ASTRA
 * Centralizes fetch handling, parses FastAPI detail error messages,
 * and preserves existing relative endpoint paths.
 */

export async function fetchApi(url, options = {}) {
  const config = {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  };

  try {
    const res = await fetch(url, config);
    let data = null;
    const contentType = res.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
      data = await res.json();
    } else {
      const text = await res.text();
      data = text ? { message: text } : {};
    }

    if (!res.ok) {
      let errorMessage = `HTTP Error ${res.status}`;
      if (data) {
        if (typeof data.detail === "string") {
          errorMessage = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMessage = data.detail.map(d => d.msg || JSON.stringify(d)).join("; ");
        } else if (data.message) {
          errorMessage = data.message;
        } else if (data.error) {
          errorMessage = data.error;
        }
      }
      const err = new Error(errorMessage);
      err.status = res.status;
      err.data = data;
      throw err;
    }

    return data;
  } catch (err) {
    if (!err.status) {
      console.error(`API Fetch Error [${url}]:`, err.message);
    }
    throw err;
  }
}

export const api = {
  get: (url, options) => fetchApi(url, { method: "GET", ...options }),
  post: (url, body, options) =>
    fetchApi(url, { method: "POST", body: body ? JSON.stringify(body) : undefined, ...options }),
  put: (url, body, options) =>
    fetchApi(url, { method: "PUT", body: body ? JSON.stringify(body) : undefined, ...options }),
  delete: (url, options) => fetchApi(url, { method: "DELETE", ...options }),
};

export default api;
