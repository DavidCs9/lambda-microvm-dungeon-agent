import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  type CognitoUserSession,
} from "amazon-cognito-identity-js";

export interface AuthSession {
  accessToken: string;
  idToken: string;
  userSub: string;
  username: string;
}

function pool(): CognitoUserPool {
  const UserPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID;
  const ClientId = import.meta.env.VITE_COGNITO_CLIENT_ID;
  if (!UserPoolId || !ClientId) {
    throw new Error(
      "Missing VITE_COGNITO_USER_POOL_ID / VITE_COGNITO_CLIENT_ID. Copy web/.env.example to web/.env.local.",
    );
  }
  return new CognitoUserPool({ UserPoolId, ClientId });
}

function sessionOf(user: CognitoUser, session: CognitoUserSession): AuthSession {
  const idPayload = session.getIdToken().decodePayload() as { sub?: unknown };
  if (typeof idPayload.sub !== "string") {
    throw new Error("Cognito session is missing the user subject.");
  }
  return {
    accessToken: session.getAccessToken().getJwtToken(),
    idToken: session.getIdToken().getJwtToken(),
    userSub: idPayload.sub,
    username: user.getUsername(),
  };
}

function sessionForUser(user: CognitoUser): Promise<AuthSession | null> {
  return new Promise((resolve, reject) => {
    user.getSession((error: Error | null, session: CognitoUserSession | null) => {
      if (error || !session || !session.isValid()) {
        resolve(null);
        return;
      }
      try {
        resolve(sessionOf(user, session));
      } catch (sessionError) {
        reject(sessionError);
      }
    });
  });
}

export async function currentAuthSession(): Promise<AuthSession | null> {
  const user = pool().getCurrentUser();
  return user ? sessionForUser(user) : null;
}

export async function accessToken(): Promise<string | null> {
  return (await currentAuthSession())?.accessToken ?? null;
}

export function signIn(email: string, password: string): Promise<AuthSession> {
  const user = new CognitoUser({ Username: email, Pool: pool() });
  const details = new AuthenticationDetails({ Username: email, Password: password });
  return new Promise((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: (session) => {
        try {
          resolve(sessionOf(user, session));
        } catch (error) {
          reject(error);
        }
      },
      onFailure: (error) => reject(error),
      newPasswordRequired: () =>
        reject(new Error("Este usuario necesita una contraseña permanente configurada por un administrador.")),
    });
  });
}

export function signOut(): void {
  pool().getCurrentUser()?.signOut();
}

export function authErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.includes("Missing VITE_COGNITO")) {
    return error.message;
  }
  if (typeof error === "object" && error !== null && "code" in error) {
    const code = (error as { code?: unknown }).code;
    if (code === "NotAuthorizedException" || code === "UserNotFoundException") {
      return "Correo o contraseña incorrectos.";
    }
    if (code === "PasswordResetRequiredException") {
      return "Este usuario necesita restablecer su contraseña desde Cognito.";
    }
  }
  return "No se pudo iniciar sesión. Inténtalo de nuevo.";
}
