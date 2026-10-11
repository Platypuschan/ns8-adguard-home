*** Settings ***
Library    SSHLibrary
Library    String

*** Variables ***
${IMAGE_URL}         ghcr.io/platypuschan/adguard-home:latest
# The update scenario starts from the last published release of this module;
# test-module-update.sh looks it up in the registry.
${PREVIOUS_IMAGE_URL}    ${EMPTY}
${SCENARIO}          install
${HOST}              adguard.test
${BLOCKED}           blocked.adguard-ci.test
${module_id}         ${EMPTY}
${node_ip}           ${EMPTY}
# Not ${admin_password}: Robot variable names ignore case, which would
# overwrite ${ADMIN_PASSWORD} of the cluster-admin login below.
${adguard_password}    ${EMPTY}
${ADMIN_USER}        admin
${ADMIN_PASSWORD}    Nethesis,1234

*** Keywords ***
Login to cluster-admin
    New Page    https://${NODE_ADDR}/cluster-admin/
    Fill Text    text="Username"    ${ADMIN_USER}
    Click    button >> text="Continue"
    Fill Text    text="Password"    ${ADMIN_PASSWORD}
    Click    button >> text="Log in"
    Wait For Elements State    css=#main-content    visible    timeout=10s

Get configuration
    ${output}    ${rc} =    Execute Command    api-cli run module/${module_id}/get-configuration
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    get-configuration failed: ${output}
    &{config} =    Evaluate    json.loads(r'''${output}''')    modules=json
    RETURN    &{config}

Read admin credentials
    &{config} =    Get configuration
    Should Be Equal    ${config.url}    https://${HOST}/
    Should Be Equal    ${config.doh_url}    https://${HOST}/dns-query
    Should Be Equal    ${config.admin_user}    admin
    Should Not Be Empty    ${config.admin_password}
    Set Suite Variable    ${adguard_password}    ${config.admin_password}

Run action
    [Arguments]    ${action}    ${payload}
    ${output}    ${rc} =    Execute Command    api-cli run module/${module_id}/${action} --data '${payload}'
    ...    return_rc=True
    RETURN    ${output}    ${rc}

Configure current module
    [Arguments]    &{extra}
    ${payload} =    Evaluate    json.dumps({"host": $HOST, "http2https": False, "lets_encrypt": False, **$extra})    modules=json
    ${output}    ${rc} =    Run action    configure-module    ${payload}
    Should Be Equal As Integers    ${rc}    0    configure-module failed: ${output}

Configure is rejected
    [Arguments]    ${error}    &{extra}
    ${payload} =    Evaluate    json.dumps({"host": $HOST, "http2https": False, "lets_encrypt": False, **$extra})    modules=json
    ${output}    ${rc} =    Run action    configure-module    ${payload}
    Should Not Be Equal As Integers    ${rc}    0
    Should Contain    ${output}    ${error}

# curl through Traefik; prints the HTTP status in the last line
Route
    [Arguments]    ${method}    ${path}    @{options}
    ${extra} =    Catenate    @{options}
    ${output}    ${rc} =    Execute Command    curl -sS --max-time 10 --resolve ${HOST}:80:127.0.0.1 -b /root/adguard.cookies -c /root/adguard.cookies -w '\\n\%{http_code}' -X ${method} ${extra} 'http://${HOST}${path}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    curl failed: ${output}
    ${body}    ${status} =    Evaluate    $output.rsplit("\\n", 1)
    RETURN    ${body}    ${status}

Login to AdGuard Home
    [Arguments]    ${password}
    Execute Command    rm -f /root/adguard.cookies
    ${payload} =    Evaluate    json.dumps({"name": "admin", "password": $password})    modules=json
    ${body}    ${status} =    Route    POST    /control/login    -H 'Content-Type: application/json'    -d '${payload}'
    RETURN    ${body}    ${status}

AdGuard Home accepts the admin login
    ${body}    ${status} =    Login to AdGuard Home    ${adguard_password}
    Should Be Equal    ${status}    200    login failed: ${body}

Wait until AdGuard Home is up
    Wait Until Keyword Succeeds    120 seconds    2 seconds    AdGuard Home accepts the admin login

Query
    [Arguments]    ${server}    ${name}    ${mode}=udp
    ${output}    ${rc} =    Execute Command    python3 /root/dnsquery.py ${server} ${name} ${mode}
    ...    return_rc=True    return_stderr=False
    RETURN    ${output}    ${rc}

Resolves
    [Arguments]    ${server}    ${name}    ${expected}    ${mode}=udp
    ${output}    ${rc} =    Query    ${server}    ${name}    ${mode}
    Should Be Equal As Integers    ${rc}    0    DNS query failed: ${output}
    Should Be Equal    ${output}    ${expected}

Container id
    ${id} =    Execute Command    runagent -m ${module_id} podman inspect --format {{.Id}} adguard
    RETURN    ${id}

Service is active
    ${rc} =    Execute Command    runagent -m ${module_id} systemctl --user is-active --quiet adguard.service
    ...    return_rc=True    return_stdout=False
    Should Be Equal As Integers    ${rc}    0    adguard.service is not active

User rules
    ${body}    ${status} =    Route    GET    /control/filtering/status
    Should Be Equal    ${status}    200    filtering status failed: ${body}
    &{filtering} =    Evaluate    json.loads(r'''${body}''')    modules=json
    RETURN    ${filtering.user_rules}

Add the blocking rule
    ${body}    ${status} =    Route    POST    /control/filtering/set_rules    -H 'Content-Type: application/json'    -d '{"rules":["||${BLOCKED}^"]}'
    Should Be Equal    ${status}    200    set_rules failed: ${body}

*** Test Cases ***
Add module for ${SCENARIO} scenario
    IF    r'${SCENARIO}' == 'update'
        Set Local Variable    ${install_image}    ${PREVIOUS_IMAGE_URL}
    ELSE
        Set Local Variable    ${install_image}    ${IMAGE_URL}
    END
    ${output}    ${rc} =    Execute Command    add-module ${install_image} 1
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    add-module ${install_image} failed: ${output}
    &{output} =    Evaluate    ast.literal_eval(r'''${output}''')    modules=ast
    Set Suite Variable    ${module_id}    ${output.module_id}
    Put File    ${CURDIR}/dnsquery.py    /root/dnsquery.py
    ${ip} =    Execute Command    ip -4 route get 1.1.1.1 | sed -n 's/.* src \\([0-9.]*\\).*/\\1/p'
    Should Match Regexp    ${ip}    ^[0-9.]+$
    Set Suite Variable    ${node_ip}    ${ip}
    # Diagnostics: what else listens on port 53 on this distribution
    ${listeners} =    Execute Command    ss -lntupH 'sport = :53'
    Log    ${listeners}    console=${True}

Configure initial module
    Configure current module
    Read admin credentials
    Wait until AdGuard Home is up
    IF    r'${SCENARIO}' == 'update'
        # A rule added before the update must survive it.
        Add the blocking rule
    END

Update module from the previous release
    Skip If    r'${SCENARIO}' != 'update'    only the update scenario updates the module
    Log    Scenario ${SCENARIO} with ${IMAGE_URL}    console=${True}
    # Same request as the Software Center: no forced pull.
    ${output}    ${rc} =    Execute Command    api-cli run update-module --data '{"module_url":"${IMAGE_URL}","instances":["${module_id}"]}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    update-module ${IMAGE_URL} failed: ${output}
    ${journal} =    Execute Command    journalctl -q --no-pager SYSLOG_IDENTIFIER=agent@${module_id}
    Should Not Contain    ${journal}    has failed    an update-module.d step failed
    ${image} =    Execute Command    runagent -m ${module_id} printenv IMAGE_URL
    ${image} =    Strip String    ${image}
    Should Be Equal    ${image}    ${IMAGE_URL}

Check service after install or update
    Read admin credentials
    Wait until AdGuard Home is up
    Service is active

Check data kept by the update
    Skip If    r'${SCENARIO}' != 'update'    only the update scenario has data from the previous release
    ${rules} =    User rules
    Should Contain    ${rules}    ||${BLOCKED}^

Web interface is served through Traefik
    ${body}    ${status} =    Route    GET    /login.html
    Should Be Equal    ${status}    200
    Should Contain    ${body}    <title>Login</title>
    # The setup wizard is never reachable: the configuration exists
    ${body}    ${status} =    Route    GET    /control/install/get_addresses
    Should Not Be Equal    ${status}    200

Wrong password is rejected
    ${body}    ${status} =    Login to AdGuard Home    not-the-password
    Should Be Equal    ${status}    403
    ${body}    ${status} =    Route    GET    /control/status
    Should Be Equal    ${status}    401

DNS is served on port 53
    AdGuard Home accepts the admin login
    Add the blocking rule
    # Blocked by the user rule (default blocking mode answers 0.0.0.0)
    Wait Until Keyword Succeeds    30 seconds    2 seconds    Resolves    127.0.0.1    ${BLOCKED}    rcode=0 a=0.0.0.0
    Resolves    127.0.0.1    ${BLOCKED}    rcode=0 a=0.0.0.0    tcp
    Resolves    ${node_ip}    ${BLOCKED}    rcode=0 a=0.0.0.0
    # Forwarded to the default upstream
    ${output}    ${rc} =    Query    ${node_ip}    example.com
    Should Be Equal As Integers    ${rc}    0    DNS query failed: ${output}
    Should Match Regexp    ${output}    ^rcode=0 a=[0-9.]+

DNS-over-HTTPS is served through Traefik
    ${wire} =    Execute Command    python3 /root/dnsquery.py - ${BLOCKED} doh-wire
    ${output}    ${rc} =    Execute Command    curl -sS --max-time 10 --resolve ${HOST}:80:127.0.0.1 -o /root/doh.bin -w '\%{http_code} \%{content_type}' 'http://${HOST}/dns-query?dns=${wire}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0
    Should Be Equal    ${output}    200 application/dns-message
    # The blocked address 0.0.0.0 is the last 4 bytes of the answer
    ${tail} =    Execute Command    tail -c 4 /root/doh.bin | od -An -tu1 | tr -s ' '
    Should Be Equal    ${tail}    ${SPACE}0 0 0 0

DNS port is open in the firewall
    ${services} =    Execute Command    firewall-cmd --list-services
    Should Contain    ${services}    ${module_id}
    ${ports} =    Execute Command    firewall-cmd --permanent --info-service=${module_id}
    Should Contain    ${ports}    53/tcp
    Should Contain    ${ports}    53/udp

Saving unchanged settings keeps AdGuard Home running
    ${before} =    Container id
    Configure current module
    ${after} =    Container id
    Should Be Equal    ${after}    ${before}    AdGuard Home was restarted although nothing changed
    ${rc} =    Execute Command    runagent -m ${module_id} test ! -e adguard-restart-needed
    ...    return_rc=True    return_stdout=False
    Should Be Equal As Integers    ${rc}    0

Admin password can be changed and rules are kept
    ${old} =    Set Variable    ${adguard_password}
    Configure current module    admin_password=ci-new-password-${SCENARIO}
    Read admin credentials
    Should Be Equal    ${adguard_password}    ci-new-password-${SCENARIO}
    Wait until AdGuard Home is up
    ${rules} =    User rules
    Should Contain    ${rules}    ||${BLOCKED}^
    ${body}    ${status} =    Login to AdGuard Home    ${old}
    Should Be Equal    ${status}    403

Listen addresses can be changed
    Configure current module    dns_bind_hosts=${{[$node_ip]}}
    &{config} =    Get configuration
    Should Be Equal    ${config.dns_bind_hosts}    ${{[$node_ip]}}
    Should Contain    ${config.node_addresses}    ${node_ip}
    Wait until AdGuard Home is up
    Wait Until Keyword Succeeds    30 seconds    2 seconds    Resolves    ${node_ip}    ${BLOCKED}    rcode=0 a=0.0.0.0
    ${output}    ${rc} =    Query    127.0.0.1    ${BLOCKED}
    Should Not Be Equal As Integers    ${rc}    0    127.0.0.1 still answers: ${output}

A busy DNS port is reported and AdGuard Home keeps running
    # Hold port 53 on 127.0.0.1, free while AdGuard Home listens on the node address only
    Execute Command    systemd-run --unit=adguard-ci-holder python3 -c 'import socket,time; u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); u.bind(("127.0.0.1",53)); t=socket.socket(); t.bind(("127.0.0.1",53)); t.listen(); time.sleep(600)'
    Sleep    2s
    Configure is rejected    dns_port_in_use    dns_bind_hosts=${{["127.0.0.1"]}}
    Service is active
    &{config} =    Get configuration
    Should Be Equal    ${config.dns_bind_hosts}    ${{[$node_ip]}}
    Wait Until Keyword Succeeds    30 seconds    2 seconds    Resolves    ${node_ip}    ${BLOCKED}    rcode=0 a=0.0.0.0
    [Teardown]    Execute Command    systemctl stop adguard-ci-holder

Invalid listen addresses are rejected
    Configure is rejected    invalid_ip_address    dns_bind_hosts=${{["not-an-ip"]}}
    Configure is rejected    ip_address_not_on_node    dns_bind_hosts=${{["192.0.2.123"]}}
    Configure is rejected    unspecified_address_must_be_alone    dns_bind_hosts=${{["0.0.0.0", $node_ip]}}
    &{config} =    Get configuration
    Should Be Equal    ${config.dns_bind_hosts}    ${{[$node_ip]}}

All addresses again
    Configure current module    dns_bind_hosts=${{["0.0.0.0"]}}
    Wait until AdGuard Home is up
    Wait Until Keyword Succeeds    30 seconds    2 seconds    Resolves    127.0.0.1    ${BLOCKED}    rcode=0 a=0.0.0.0

Check private files
    ${modes} =    Execute Command    runagent -m ${module_id} stat -c '%a' adguard.json conf conf/AdGuardHome.yaml
    Should Be Equal    ${modes}    600\n700\n600
    ${environment} =    Execute Command    runagent -m ${module_id} cat environment
    Should Not Contain    ${environment}    ${adguard_password}
    Should Not Contain    ${environment}    PASSWORD
    ${yaml} =    Execute Command    runagent -m ${module_id} cat conf/AdGuardHome.yaml
    Should Not Contain    ${yaml}    ${adguard_password}

Backup includes settings and the AdGuard Home configuration
    ${include} =    Execute Command    runagent -m ${module_id} sh -c 'cat ../etc/state-include.conf'
    FOR    ${line}    IN    state/adguard.json    state/conf/AdGuardHome.yaml    volumes/adguard-work/userfilters
        Should Match Regexp    ${include}    (?m)^${line}$
    END

Module UI loads in cluster-admin
    [Tags]    ui
    Import Library    Browser
    New Browser    chromium    headless=True
    New Context    ignoreHTTPSErrors=True
    Login to cluster-admin
    Go To    https://${NODE_ADDR}/cluster-admin/#/apps/${module_id}
    Wait For Elements State    iframe >>> h2 >> text="Status"    visible    timeout=20s
    Take Screenshot    filename=${OUTPUT DIR}/browser/screenshot/1._Status.png
    Go To    https://${NODE_ADDR}/cluster-admin/#/apps/${module_id}?page=settings
    Wait For Elements State    iframe >>> h2 >> text="Settings"    visible    timeout=20s
    # The heading renders even when module tasks fail; the fields are only
    # enabled and filled after get-configuration has completed
    Wait For Elements State    iframe >>> input[placeholder="adguard.example.org"]    enabled    timeout=30s
    Get Property    iframe >>> input[placeholder="adguard.example.org"]    value    ==    ${HOST}
    Get Property    iframe >>> input#adguard-url    value    ==    https://${HOST}/
    Get Property    iframe >>> input#adguard-admin-user    value    ==    admin
    Get Property    iframe >>> input#adguard-admin-password    type    ==    password
    Get Property    iframe >>> input#adguard-doh-url    value    ==    https://${HOST}/dns-query
    Get Property    iframe >>> input#dns-bind-hosts    value    ==    0.0.0.0
    Take Screenshot    filename=${OUTPUT DIR}/browser/screenshot/2._Settings.png
    Close Browser

Remove module
    ${rc} =    Execute Command    remove-module --no-preserve ${module_id}
    ...    return_rc=True    return_stdout=False
    Should Be Equal As Integers    ${rc}    0
    ${services} =    Execute Command    firewall-cmd --list-services
    Should Not Contain    ${services}    ${module_id}
    ${output}    ${rc} =    Query    127.0.0.1    ${BLOCKED}
    Should Not Be Equal As Integers    ${rc}    0    DNS still answers after removal: ${output}
