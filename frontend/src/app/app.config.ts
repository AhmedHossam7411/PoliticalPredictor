import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withInterceptors, HttpInterceptorFn } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';

// Attach the session token to every request; on a 401 (expired/invalid), drop the
// token and reload to the login screen.
const authInterceptor: HttpInterceptorFn = (req, next) => {
  const token = sessionStorage.getItem('pp_token');
  const authed = token
    ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    : req;
  return next(authed).pipe(
    catchError((err) => {
      if (err.status === 401 && !req.url.includes('/auth/login')) {
        sessionStorage.removeItem('pp_token');
        location.reload();
      }
      return throwError(() => err);
    }),
  );
};

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(withInterceptors([authInterceptor])),
  ]
};
