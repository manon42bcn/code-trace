"""Static dependency fixture; Code RAG indexes this file without executing it."""

from behave import given


@given('a registered user')
def registered_user(context):
    context.registered_user = {'username': 'demo'}
