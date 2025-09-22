Name:           testrpm
Version:        0.1
Release:        1%{?dist}
Summary:        A simple test RPM package with various URLs

License:        MIT

# Various URL formats for testing
# Git URLs
%global repo_url    GIT://github.com/example/testrpm.git
%global alt_repo    git://gitlab.com/example/testrpm.git

# HTTP URLs
%global http_url    HTTP://downloads.example.com/packages/testrpm
%global https_url   HTTPS://secure.example.com/downloads/testrpm

URL:            %{https_url}
Source0:        %{http_url}/testrpm-%{version}.tar.gz
Source1:        %{http_url}/testrpm-%{version}.tar.gz.sig

BuildArch:      noarch

%description
This is a simple test RPM package for testing purposes.
It includes references to git://example.com/repo and
https://example.com/documentation for testing URL extraction.
The package is hosted at %{repo_url} with mirror at %{alt_repo}.

%prep
%autosetup -n testrpm-%{version} -S git
# Clone dependencies
git clone %{repo_url} main-repo
git clone %{alt_repo} backup-repo

# URLs in comments and descriptions
# This is a comment with https://example.com/docs and http://example.org/help

%build
# no-op
# Download tools from HTTPS://build-resources.example.com/tools

%install
mkdir -p %{buildroot}%{_bindir}
touch %{buildroot}%{_bindir}/testrpm
# Get config from http://configs.example.com/testrpm?version=0.1

%files
%{_bindir}/testrpm

%changelog
* Wed Oct 01 2024 Your Name <your.email@testrpmexample.com> - 0.1-1
- Initial package
- Added support for https://feature.example.com
