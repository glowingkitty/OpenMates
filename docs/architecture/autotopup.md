# Auto Top Up architecture

## Requirements

- user can activate auto top up during signup or in the settings menu
- auto top up on low balance and auto top up every month can be done independently
- stripe payment method ID is stored encrypted during signup, so it can be used later in settings menu (but requires entering 2FA OTP code to confirm)
- settings:
    - user must be able to activate/deactivate auto top up any time
    - user must be able to change which credits amount to top up
    - user must be able to purchase with existing or new payment method