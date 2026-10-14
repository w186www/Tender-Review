import type { ReactNode } from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { errorText, readToken, setToken } from "./api/client";
import { api, type Identity } from "./api/operations";

type AuthValue = {
  identity: Identity | null;
  loading: boolean;
  error: string | null;
  signIn: (
    tenant: string,
    username: string,
    password: string,
  ) => Promise<boolean>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadIdentity = useCallback(async () => {
    if (!readToken()) {
      setIdentity(null);
      setLoading(false);
      return;
    }
    try {
      setIdentity(await api.identity());
    } catch (reason) {
      setToken(null);
      setIdentity(null);
      setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadIdentity();
    const expire = () => {
      setIdentity(null);
      setLoading(false);
    };
    window.addEventListener("auth:expired", expire);
    return () => window.removeEventListener("auth:expired", expire);
  }, [loadIdentity]);

  const signIn = useCallback(
    async (tenant: string, username: string, password: string) => {
      setError(null);
      setLoading(true);
      try {
        const token = await api.login(tenant, username, password);
        setToken(token.access_token);
        setIdentity(await api.identity());
        return true;
      } catch (reason) {
        setToken(null);
        setIdentity(null);
        setError(errorText(reason));
        return false;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const signOut = useCallback(async () => {
    try {
      if (readToken()) await api.logout();
    } catch {
      // Clear local state even if the network is unavailable; the UI never claims server revocation.
    } finally {
      setToken(null);
      setIdentity(null);
    }
  }, []);

  const value = useMemo(
    () => ({ identity, loading, error, signIn, signOut }),
    [identity, loading, error, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
