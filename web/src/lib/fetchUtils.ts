export const getErrorMsg = async (response: Response) => {
  if (response.ok) {
    return null;
  }
  const responseJson = await response.json();
  return responseJson.message || responseJson.detail || "Unknown error";
};

export async function fetchWithCredentials(url: string, options: RequestInit = {}) {
  const defaultOptions: RequestInit = {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const mergedOptions = {
    ...defaultOptions,
    ...options,
    headers: {
      ...defaultOptions.headers,
      ...options.headers,
    },
  };

  return fetch(url, mergedOptions);
}
