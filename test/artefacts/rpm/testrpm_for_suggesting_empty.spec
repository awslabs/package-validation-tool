Name:           testrpm_for_suggesting_empty
Version:        0.1
Release:        1%{?dist}
Summary:        A test RPM package with no archive Sources

License:        MIT
URL:            https://testrpmexample.com/testrpm_for_suggesting_empty

# In some cases, the package doesn't have any archives at all (e.g., pure
# configuration packages). Emulate such case.
Source0:        some-config.json
Source1234:     some-license.pdf

BuildArch:      noarch

%description
This is a test RPM package with no archive Sources for testing purposes.

%prep
%autosetup

%build
# no-op

%install
mkdir -p %{buildroot}%{_bindir}
touch %{buildroot}%{_bindir}/testrpm_for_suggesting_empty

%files
%{_bindir}/testrpm_for_suggesting_empty

%changelog
* Wed Oct 01 2024 Your Name <your.email@testrpmexample.com> - 0.1-1
- Initial package


