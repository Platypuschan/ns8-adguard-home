<!--
  Copyright (C) 2022 Nethesis S.r.l.
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <cv-grid fullWidth>
    <cv-row>
      <cv-column class="page-title">
        <h2>{{ $t("settings.title") }}</h2>
      </cv-column>
    </cv-row>
    <cv-row v-if="error.getConfiguration">
      <cv-column>
        <NsInlineNotification
          kind="error"
          :title="$t('action.get-configuration')"
          :description="error.getConfiguration"
          :showCloseButton="false"
        />
      </cv-column>
    </cv-row>
    <!-- web interface login -->
    <cv-row v-if="url">
      <cv-column>
        <cv-tile light>
          <h4 class="mg-bottom">{{ $t("settings.web_title") }}</h4>
          <p class="mg-bottom helper">
            {{ $t("settings.web_description") }}
          </p>
          <cv-text-input
            id="adguard-url"
            :label="$t('settings.web_url')"
            :value="url"
            readonly
            class="mg-bottom"
          />
          <cv-text-input
            id="adguard-admin-user"
            :label="$t('settings.admin_user')"
            :value="adminUser"
            readonly
            class="mg-bottom"
          />
          <cv-text-input
            id="adguard-admin-password"
            :label="$t('settings.admin_password')"
            :value="adminPassword"
            type="password"
            readonly
            class="mg-bottom"
          />
          <cv-text-input
            id="adguard-doh-url"
            :label="$t('settings.doh_url')"
            :helper-text="$t('settings.doh_url_helper')"
            :value="dohUrl"
            readonly
            class="mg-bottom"
          />
          <NsButton kind="secondary" :icon="Launch20" @click="openWebUi">{{
            $t("settings.open_web")
          }}</NsButton>
        </cv-tile>
      </cv-column>
    </cv-row>
    <cv-row>
      <cv-column>
        <cv-tile light>
          <cv-form @submit.prevent="configureModule">
            <cv-text-input
              :label="$t('settings.adguard_fqdn')"
              placeholder="adguard.example.org"
              v-model.trim="host"
              class="mg-bottom"
              :invalid-message="$t(error.host)"
              :disabled="loading.getConfiguration || loading.configureModule"
              ref="host"
            >
            </cv-text-input>
            <cv-toggle
              value="letsEncrypt"
              :label="$t('settings.lets_encrypt')"
              v-model="isLetsEncryptEnabled"
              :disabled="loading.getConfiguration || loading.configureModule"
              class="mg-bottom"
            >
              <template slot="text-left">{{
                $t("settings.disabled")
              }}</template>
              <template slot="text-right">{{
                $t("settings.enabled")
              }}</template>
            </cv-toggle>
            <cv-toggle
              value="httpToHttps"
              :label="$t('settings.http_to_https')"
              v-model="isHttpToHttpsEnabled"
              :disabled="loading.getConfiguration || loading.configureModule"
              class="mg-bottom"
            >
              <template slot="text-left">{{
                $t("settings.disabled")
              }}</template>
              <template slot="text-right">{{
                $t("settings.enabled")
              }}</template>
            </cv-toggle>
            <!-- DNS listen addresses -->
            <cv-text-input
              id="dns-bind-hosts"
              :label="$t('settings.dns_bind_hosts')"
              :helper-text="dnsBindHostsHelper"
              placeholder="0.0.0.0"
              v-model.trim="dnsBindHosts"
              :invalid-message="$t(error.dns_bind_hosts)"
              :disabled="loading.getConfiguration || loading.configureModule"
              class="mg-bottom"
              ref="dns_bind_hosts"
            />
            <!-- admin password -->
            <cv-text-input
              id="new-admin-password"
              :label="$t('settings.new_admin_password')"
              :helper-text="$t('settings.new_admin_password_helper')"
              v-model="newAdminPassword"
              type="password"
              autocomplete="new-password"
              :invalid-message="$t(error.admin_password)"
              :disabled="loading.getConfiguration || loading.configureModule"
              class="mg-bottom"
              ref="admin_password"
            />
            <cv-row v-if="error.configureModule">
              <cv-column>
                <NsInlineNotification
                  kind="error"
                  :title="$t('action.configure-module')"
                  :description="error.configureModule"
                  :showCloseButton="false"
                />
              </cv-column>
            </cv-row>
            <NsButton
              kind="primary"
              :icon="Save20"
              :loading="loading.configureModule"
              :disabled="loading.getConfiguration || loading.configureModule"
              >{{ $t("settings.save") }}</NsButton
            >
          </cv-form>
        </cv-tile>
      </cv-column>
    </cv-row>
  </cv-grid>
</template>

<script>
import to from "await-to-js";
import { mapState } from "vuex";
import {
  QueryParamService,
  UtilService,
  TaskService,
  IconService,
  PageTitleService,
} from "@nethserver/ns8-ui-lib";

export default {
  name: "Settings",
  mixins: [
    TaskService,
    IconService,
    UtilService,
    QueryParamService,
    PageTitleService,
  ],
  pageTitle() {
    return this.$t("settings.title") + " - " + this.appName;
  },
  data() {
    return {
      q: {
        page: "settings",
      },
      urlCheckInterval: null,
      host: "",
      isLetsEncryptEnabled: false,
      isHttpToHttpsEnabled: true,
      url: "",
      dohUrl: "",
      adminUser: "",
      adminPassword: "",
      newAdminPassword: "",
      // Comma-separated list of IP addresses
      dnsBindHosts: "",
      nodeAddresses: [],
      loading: {
        getConfiguration: false,
        configureModule: false,
      },
      error: {
        getConfiguration: "",
        configureModule: "",
        host: "",
        lets_encrypt: "",
        http2https: "",
        admin_password: "",
        dns_bind_hosts: "",
      },
    };
  },
  computed: {
    ...mapState(["instanceName", "core", "appName"]),
    dnsBindHostsHelper() {
      let text = this.$t("settings.dns_bind_hosts_helper");
      if (this.nodeAddresses.length) {
        text +=
          " " +
          this.$t("settings.node_addresses", {
            addresses: this.nodeAddresses.join(", "),
          });
      }
      return text;
    },
  },
  created() {
    this.getConfiguration();
  },
  beforeRouteEnter(to, from, next) {
    next((vm) => {
      vm.watchQueryData(vm);
      vm.urlCheckInterval = vm.initUrlBindingForApp(vm, vm.q.page);
    });
  },
  beforeRouteLeave(to, from, next) {
    clearInterval(this.urlCheckInterval);
    next();
  },
  methods: {
    // Start a module task and route its events to the given handlers
    async runTask(action, data, handlers, extra) {
      const eventId = this.getUuid();
      this.core.$root.$once(`${action}-aborted-${eventId}`, handlers.aborted);
      this.core.$root.$once(
        `${action}-completed-${eventId}`,
        handlers.completed
      );
      if (handlers.validationFailed) {
        this.core.$root.$once(
          `${action}-validation-failed-${eventId}`,
          handlers.validationFailed
        );
      }
      const res = await to(
        this.createModuleTaskForApp(this.instanceName, {
          action,
          data,
          extra: {
            title: this.$t("action." + action),
            isNotificationHidden: true,
            ...extra,
            eventId,
          },
        })
      );
      return res[0];
    },
    focusElement(ref) {
      const element = this.$refs[ref];
      if (element && element.focus) {
        element.focus();
      }
    },
    openWebUi() {
      window.open(this.url, "_blank", "noopener");
    },
    bindHostList() {
      return this.dnsBindHosts
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter((item) => item);
    },
    async getConfiguration() {
      this.loading.getConfiguration = true;
      this.error.getConfiguration = "";
      const err = await this.runTask("get-configuration", undefined, {
        aborted: this.getConfigurationAborted,
        completed: this.getConfigurationCompleted,
      });
      if (err) {
        console.error("error creating task get-configuration", err);
        this.error.getConfiguration = this.getErrorMessage(err);
        this.loading.getConfiguration = false;
      }
    },
    getConfigurationAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.getConfiguration = this.$t("error.generic_error");
      this.loading.getConfiguration = false;
    },
    getConfigurationCompleted(taskContext, taskResult) {
      const config = taskResult.output;
      this.host = config.host;
      this.isLetsEncryptEnabled = config.lets_encrypt;
      this.isHttpToHttpsEnabled = config.http2https;
      this.url = config.url;
      this.dohUrl = config.doh_url;
      this.adminUser = config.admin_user;
      this.adminPassword = config.admin_password;
      this.dnsBindHosts = config.dns_bind_hosts.join(", ");
      this.nodeAddresses = config.node_addresses;
      this.newAdminPassword = "";
      this.loading.getConfiguration = false;
      this.$nextTick(() => this.focusElement("host"));
    },
    validateConfigureModule() {
      this.clearErrors(this);
      let firstInvalid = "";
      if (!this.host) {
        this.error.host = "common.required";
        firstInvalid = "host";
      }
      if (!this.bindHostList().length) {
        this.error.dns_bind_hosts = "common.required";
        firstInvalid = firstInvalid || "dns_bind_hosts";
      }
      if (
        this.newAdminPassword &&
        new TextEncoder().encode(this.newAdminPassword).length > 72
      ) {
        this.error.admin_password = "settings.password_too_long";
        firstInvalid = firstInvalid || "admin_password";
      }
      if (firstInvalid) {
        this.$nextTick(() => this.focusElement(firstInvalid));
        return false;
      }
      return true;
    },
    // Show task validation errors next to their fields
    showValidationErrors(validationErrors) {
      let firstInvalid = "";
      for (const validationError of validationErrors) {
        // "dns_bind_hosts.1" belongs to the dns_bind_hosts field
        const param = validationError.parameter.split(".")[0];
        let message = "settings." + validationError.error;
        if (param === "dns_bind_hosts" && validationError.value) {
          message = this.$t(message) + ": " + validationError.value;
        }
        this.error[param] = message;
        firstInvalid = firstInvalid || param;
      }
      if (firstInvalid) {
        this.$nextTick(() => this.focusElement(firstInvalid));
      }
    },
    async configureModule() {
      if (!this.validateConfigureModule()) {
        return;
      }
      this.loading.configureModule = true;
      const data = {
        host: this.host,
        lets_encrypt: this.isLetsEncryptEnabled,
        http2https: this.isHttpToHttpsEnabled,
        dns_bind_hosts: this.bindHostList(),
      };
      if (this.newAdminPassword) {
        data.admin_password = this.newAdminPassword;
      }
      const err = await this.runTask(
        "configure-module",
        data,
        {
          aborted: this.configureModuleAborted,
          completed: this.configureModuleCompleted,
          validationFailed: this.configureModuleValidationFailed,
        },
        {
          title: this.$t("settings.instance_configuration", {
            instance: this.instanceName,
          }),
          description: this.$t("settings.configuring"),
          isNotificationHidden: false,
        }
      );
      if (err) {
        console.error("error creating task configure-module", err);
        this.error.configureModule = this.getErrorMessage(err);
        this.loading.configureModule = false;
      }
    },
    configureModuleValidationFailed(validationErrors) {
      this.loading.configureModule = false;
      this.showValidationErrors(validationErrors);
    },
    configureModuleAborted(taskResult, taskContext) {
      console.error(`${taskContext.action} aborted`, taskResult);
      this.error.configureModule = this.$t("error.generic_error");
      this.loading.configureModule = false;
    },
    configureModuleCompleted() {
      this.loading.configureModule = false;
      this.getConfiguration();
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";

.mg-bottom {
  margin-bottom: $spacing-06;
}

.helper {
  max-width: 38rem;
}
</style>
