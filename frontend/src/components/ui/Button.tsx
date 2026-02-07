import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type ButtonVariant =
  | "primary"
  | "secondary"
  | "destructive"
  | "success"
  | "muted"
  | "ghost"
  | "link"
  | "tab";

type ButtonSize = "sm" | "md" | "lg" | "icon" | "tab";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const baseClasses =
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50";

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:opacity-90",
  secondary: "bg-secondary text-secondary-foreground hover:opacity-80",
  destructive: "bg-destructive text-destructive-foreground hover:opacity-90",
  success: "bg-green-600 text-white hover:bg-green-700 dark:bg-green-600 dark:hover:bg-green-700",
  muted:
    "border border-border bg-muted text-foreground hover:bg-accent hover:shadow-sm dark:hover:bg-white/10 dark:hover:border-white/20 dark:hover:shadow-md",
  ghost: "bg-transparent text-foreground hover:bg-accent",
  link: "bg-transparent text-muted-foreground underline hover:text-foreground",
  tab:
    "rounded-none bg-transparent text-muted-foreground hover:text-foreground data-[active=true]:border-b-2 data-[active=true]:border-primary data-[active=true]:text-primary",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 px-3",
  md: "h-9 px-3",
  lg: "h-10 px-4",
  icon: "h-9 w-9",
  tab: "h-10 px-4",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "secondary", size = "md", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(baseClasses, variantClasses[variant], sizeClasses[size], className)}
      {...props}
    />
  ),
);

Button.displayName = "Button";
