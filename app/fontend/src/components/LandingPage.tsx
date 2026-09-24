import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  Eye,
  EyeSlash,
  LockKey,
  PaperPlaneTilt,
  ShieldCheck,
  SpinnerGap,
} from "@phosphor-icons/react";
import { loginCustomer, type AuthUser } from "../services/auth";
import { BrandMark } from "./BrandMark";

interface LandingPageProps {
  onLoginSuccess: (user: AuthUser) => void;
}

const dingtalkLoginUrl = "/api/auth/dingtalk/start";

export function LandingPage({ onLoginSuccess }: LandingPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const dingtalkError = params.get("dingtalk_error");
    if (dingtalkError) {
      setError(dingtalkError);
      params.delete("dingtalk_error");
      const query = params.toString();
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
    }
    emailRef.current?.focus();
  }, []);

  const submitLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setSubmitting(true);
    try {
      const user = await loginCustomer(email, password);
      onLoginSuccess(user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "We could not sign you in. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="landing-page login-command-page">
      <section className="login-command-visual" aria-label="Kairay Golf product asset collection">
        <picture>
          <source
            media="(min-width: 1181px)"
            type="image/webp"
            srcSet="/assets/login-command-center-720.v2.webp 720w, /assets/login-command-center-1080.v2.webp 1080w"
            sizes="50vw"
          />
          <img
            src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
            width="720"
            height="894"
            fetchPriority="high"
            decoding="async"
            alt="Kairay Golf leather headcover collection in the asset archive"
          />
        </picture>
      </section>

      <section className="login-command-auth" aria-labelledby="login-title">
        <div className="login-command-content">
          <BrandMark className="login-command-brand" subtitle="Client Catalog & Orders" />

          <div className="login-command-kicker">
            <ShieldCheck size={18} weight="bold" aria-hidden="true" />
            <span>KAIRAY GOLF · CLIENT CATALOG</span>
          </div>

          <header className="login-command-heading">
            <h1 id="login-title">See products. Build your order.</h1>
            <p>Sign in with your business email to check your catalog and order online.</p>
          </header>

          <form className="login-command-form" onSubmit={submitLogin}>
            <label>
              <span>Business email</span>
              <span className="login-command-input">
                <input
                  ref={emailRef}
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@company.com"
                  autoComplete="email"
                  required
                />
              </span>
            </label>

            <label>
              <span>Password</span>
              <span className="login-command-input has-action">
                <input
                  type={passwordVisible ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  minLength={6}
                  required
                />
                <button
                  type="button"
                  onClick={() => setPasswordVisible((visible) => !visible)}
                  aria-label={passwordVisible ? "Hide password" : "Show password"}
                  aria-pressed={passwordVisible}
                >
                  {passwordVisible
                    ? <EyeSlash size={21} weight="regular" aria-hidden="true" />
                    : <Eye size={21} weight="regular" aria-hidden="true" />}
                </button>
              </span>
            </label>

            {error && <p className="login-message is-error" role="alert">{error}</p>}
            {notice && <p className="login-message" role="status">{notice}</p>}

            <div className="login-form-options">
              <button
                type="button"
                onClick={() => setNotice("Contact your KAIRAY GOLF representative to reset your password.")}
              >
                Forgot password?
              </button>
            </div>

            <button className="login-submit" type="submit" disabled={submitting}>
              {submitting
                ? <><SpinnerGap size={20} weight="bold" /> Signing in</>
                : <>Open my catalog <ArrowRight size={20} weight="bold" /></>}
            </button>
          </form>

          <div className="login-secondary-actions">
            <p className="login-support">
              Need an account? <a href="mailto:info@craftsmangolf.com">Contact Client Service</a>
            </p>
            <a
              className="login-dingtalk-link"
              href={dingtalkLoginUrl}
              aria-label="Sign in with DingTalk"
              title="Sign in with DingTalk"
            >
              <PaperPlaneTilt size={17} weight="fill" aria-hidden="true" />
            </a>
          </div>
        </div>

        <footer className="login-command-security">
          <span className="login-command-security-icon">
            <LockKey size={19} weight="regular" aria-hidden="true" />
          </span>
          <span>Secure access for approved clients and partners</span>
        </footer>
      </section>
    </main>
  );
}
