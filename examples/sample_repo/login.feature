Feature: Authentication
  @smoke
  Scenario: Valid user
    Given a registered user
    When the user signs in
    Then the dashboard is displayed

  Scenario Outline: Wrong password
    When I sign in with <password>
    Then access is rejected
    Examples:
      | password |
      | invalid  |
